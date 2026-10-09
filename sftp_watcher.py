# -*- coding: utf-8 -*-
# =============================================================================
# FTP Watcher
# Surveille un repertoire distant SFTP, telecharge les nouveaux fichiers,
# les imprime (optionnel) et les archive localement.
#
# Ce script est concu pour fonctionner comme un service Windows (via NSSM).
# Il gere le verrou mono-instance, la stabilite des fichiers, la reprise
# sur erreur, la reconnexion SFTP et le suivi des fichiers deja traites.
#
# Configuration : voir config.example.json
# =============================================================================

import paramiko
import logging
import time
import os
import sys
import json
import signal
import posixpath
import shutil
import subprocess
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime


# =============================================================================
#  GESTION DU SIGNAL D ARRET
# =============================================================================

_arreter = False


def _handler_signal(signum, frame):
    global _arreter
    _arreter = True
    logging.info("Signal arret recu (%s). Arret propre en cours...", signum)
    logging.debug("Flag _arreter passe a True.")


signal.signal(signal.SIGINT, _handler_signal)
signal.signal(signal.SIGTERM, _handler_signal)


# =============================================================================
#  CHARGEMENT ET VALIDATION DE LA CONFIGURATION
# =============================================================================

CLES_OBLIGATOIRES = {
    "hostname": str,
    "port": int,
    "username": str,
    "known_hosts_file": str,
    "remote_path": str,
    "local_path": str,
    "archive_dir": str,
    "extensions_valides": list,
    "check_interval": (int, float),
    "temps_attente": (int, float),
    "retries": int,
    "retries_stabilite": int,
    "log_file": str,
    "log_level": str,
    "lock_file": str,
    "state_file": str,
    "activer_logs": bool,
}


def charger_config(config_file):
    if not os.path.isfile(config_file):
        raise FileNotFoundError("Fichier de configuration introuvable : %s" % config_file)
    with open(config_file, "r", encoding="utf-8") as f:
        return json.load(f)


def valider_config(config):
    erreurs = []

    for cle, type_attendu in CLES_OBLIGATOIRES.items():
        if cle not in config:
            erreurs.append("Cle manquante : '%s'" % cle)
            continue
        if not isinstance(config[cle], type_attendu):
            erreurs.append(
                "Cle '%s' : type attendu %s, recu %s"
                % (cle, type_attendu, type(config[cle]))
            )

    if "check_interval" in config and config["check_interval"] <= 0:
        erreurs.append("'check_interval' doit etre > 0")
    if "temps_attente" in config and config["temps_attente"] <= 0:
        erreurs.append("'temps_attente' doit etre > 0")
    if "retries" in config and config["retries"] < 1:
        erreurs.append("'retries' doit etre >= 1")

    confirmations = config.get("stability_confirmations", 2)
    if confirmations < 1:
        erreurs.append("'stability_confirmations' doit etre >= 1")

    if "retries_stabilite" in config and config["retries_stabilite"] < (confirmations + 1):
        erreurs.append(
            "'retries_stabilite' doit etre >= %s (confirmations=%s + 1)"
            % (confirmations + 1, confirmations)
        )

    if not config.get("password") and not config.get("private_key_path"):
        erreurs.append("Aucune authentification : 'password' ou 'private_key_path' requis")

    if config.get("private_key_path") and not os.path.isfile(config["private_key_path"]):
        erreurs.append("Cle privee introuvable : %s" % config["private_key_path"])

    if config.get("known_hosts_file") and not os.path.isfile(config["known_hosts_file"]):
        erreurs.append("Fichier known_hosts introuvable : %s" % config["known_hosts_file"])

    if config.get("local_path") and not os.path.isdir(config["local_path"]):
        erreurs.append("Dossier local introuvable : %s" % config["local_path"])

    if config.get("imprimer_fichier"):
        if not config.get("printer_name"):
            erreurs.append("'printer_name' requis si 'imprimer_fichier' est True")
        if not config.get("pdf_to_printer_path"):
            erreurs.append("'pdf_to_printer_path' requis si 'imprimer_fichier' est True")

    if erreurs:
        raise ValueError("Configuration invalide :\n  - " + "\n  - ".join(erreurs))


# =============================================================================
#  LOGGER
# =============================================================================

def setup_logger(config):
    log_file = config["log_file"]
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    if config.get("activer_logs", True):
        handler = TimedRotatingFileHandler(
            log_file,
            when="midnight",
            interval=1,
            backupCount=config.get("log_backup_count", 30),
            encoding="utf-8",
        )
        handler.suffix = "%Y-%m-%d.log"

        niveaux = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }
        level = niveaux.get(config["log_level"].upper(), logging.INFO)

        logging.basicConfig(
            level=level,
            handlers=[handler],
            format="%(asctime)s - %(levelname)s - %(message)s",
        )
        logging.info("======================================================================")
        logging.info("Demarrage de FTP Watcher")
        logging.info("PID             : %s", os.getpid())
        logging.info("Paramiko        : %s", getattr(paramiko, "__version__", "unknown"))
        logging.info("Serveur SFTP    : %s:%s", config["hostname"], config["port"])
        logging.info("Surveillance de : %s", config["remote_path"])
        logging.info("Telechargement  : %s", config["local_path"])
        logging.info("Archives        : %s", config["archive_dir"])
        logging.info("Extensions      : %s", config["extensions_valides"])
        logging.info("======================================================================")
        logging.debug("Niveau de log actif : %s", config["log_level"].upper())
        logging.debug("Intervalle de scan : %s s", config["check_interval"])
        logging.debug("Retries connexion SFTP : %s", config["retries"])
        logging.debug("Retries stabilite fichier : %s", config["retries_stabilite"])
        logging.debug("Confirmations stabilite : %s", config.get("stability_confirmations", 2))
        logging.debug("Temps attente stabilite : %s s", config["temps_attente"])
        logging.debug("Impression : %s", config.get("imprimer_fichier", False))
        logging.debug("Archivage : %s", config.get("archiver_fichier", True))
    else:
        logging.disable(logging.CRITICAL)


# =============================================================================
#  VERROU MONO-INSTANCE
# =============================================================================

def verifier_instance_unique(lock_file):
    lock_dir = os.path.dirname(lock_file)
    if lock_dir:
        os.makedirs(lock_dir, exist_ok=True)

    try:
        f = open(lock_file, "w")
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        f.write("PID=%s - Demarre le %s\n" % (os.getpid(), datetime.now()))
        f.flush()
        return f
    except (IOError, OSError) as e:
        print("ERREUR : une autre instance tourne deja (%s). Arret." % e)
        sys.exit(1)


# =============================================================================
#  ETAT PERSISTANT (fichiers deja traites)
# =============================================================================

def charger_state(state_file):
    if not os.path.isfile(state_file):
        return {}
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.error("Impossible de charger le state %s : %s", state_file, e)
        return {}


def sauver_state(state_file, state):
    try:
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logging.error("Impossible de sauver le state %s : %s", state_file, e)


def purger_state(state, retention_jours=30):
    seuil = time.time() - (retention_jours * 86400)
    a_supprimer = [k for k, v in state.items() if v < seuil]
    for k in a_supprimer:
        del state[k]
    if a_supprimer:
        logging.debug("State purge : %s entree(s) ancienne(s).", len(a_supprimer))


# =============================================================================
#  CONNEXION SFTP
# =============================================================================

def connecter_sftp(config):
    logging.debug(
        "Sequence de connexion SFTP vers %s:%s (max %s tentatives).",
        config["hostname"], config["port"], config["retries"]
    )

    for tentative in range(config["retries"]):
        logging.debug("Tentative SFTP %s/%s...", tentative + 1, config["retries"])
        try:
            ssh = paramiko.SSHClient()
            ssh.load_host_keys(config["known_hosts_file"])
            ssh.set_missing_host_key_policy(paramiko.RejectPolicy())

            if config.get("private_key_path"):
                logging.debug("Auth par cle privee : %s", config["private_key_path"])
                ssh.connect(
                    config["hostname"],
                    config["port"],
                    config["username"],
                    key_filename=config["private_key_path"],
                    timeout=30,
                )
            else:
                logging.debug("Auth par mot de passe (user=%s)", config["username"])
                ssh.connect(
                    config["hostname"],
                    config["port"],
                    config["username"],
                    password=config["password"],
                    timeout=30,
                )

            transport = ssh.get_transport()
            if transport is not None:
                transport.set_keepalive(30)
                logging.debug("Keepalive SSH active (30 s).")

            sftp = ssh.open_sftp()
            logging.info("Connexion SFTP reussie.")
            return ssh, sftp

        except Exception as e:
            logging.error(
                "Erreur connexion SFTP (tentative %s/%s) : %s",
                tentative + 1,
                config["retries"],
                e,
            )
            if tentative < config["retries"] - 1:
                time.sleep(5)
            else:
                logging.error("Echec de toutes les tentatives de connexion.")
                return None, None


def connexion_sftp_active(ssh, sftp):
    try:
        if ssh is None or sftp is None:
            return False

        transport = ssh.get_transport()
        if transport is None or not transport.is_active():
            return False

        canal = sftp.get_channel()
        if canal is None or canal.closed:
            return False

        return True
    except Exception:
        return False


# =============================================================================
#  VERIFICATION DE STABILITE D UN FICHIER DISTANT
# =============================================================================

def attendre_fichier_stable(sftp, chemin_distant, temps_attente, retries, confirmations=2):
    precedent = None
    nb_ok = 0

    for i in range(retries):
        try:
            st = sftp.stat(chemin_distant)
            courant = (st.st_size, int(st.st_mtime))
        except OSError as e:
            logging.debug("Stabilite %s : stat impossible (%s)", chemin_distant, e)
            return False

        logging.debug(
            "Stabilite %s : check %s/%s -> (size=%s, mtime=%s)",
            chemin_distant, i + 1, retries, courant[0], courant[1]
        )

        if courant == precedent:
            nb_ok += 1
            logging.debug("Stabilite %s : confirmation %s/%s", chemin_distant, nb_ok, confirmations)
            if nb_ok >= confirmations:
                logging.debug("Stabilite %s : fichier STABLE.", chemin_distant)
                return True
        else:
            nb_ok = 0
            precedent = courant

        time.sleep(temps_attente)

    logging.warning(
        "Fichier %s : taille/mtime instable apres %s verifications.",
        chemin_distant, retries,
    )
    return False


# =============================================================================
#  TELECHARGEMENT
# =============================================================================

def telecharger_fichier(sftp, chemin_distant, chemin_local):
    chemin_temp = chemin_local + ".downloading"

    logging.debug("Telechargement : source = %s", chemin_distant)
    logging.debug("Telechargement : cible = %s", chemin_local)

    t_debut = time.time()
    sftp.get(chemin_distant, chemin_temp)
    duree = time.time() - t_debut

    taille = os.path.getsize(chemin_temp)
    logging.debug(
        "Telechargement termine en %.3f s (%s octets, %.0f octets/s)",
        duree, taille, taille / duree if duree > 0 else 0
    )

    # Renommer le .downloading en nom final (atomique)
    os.replace(chemin_temp, chemin_local)


# =============================================================================
#  IMPRESSION
# =============================================================================

def imprimer_fichier(config, chemin_local):
    if not config.get("imprimer_fichier", False):
        return True

    pdf_to_printer = config["pdf_to_printer_path"]
    printer_name = config["printer_name"]

    if not os.path.isfile(pdf_to_printer):
        logging.error("PDFtoPrinter introuvable : %s", pdf_to_printer)
        return False

    if not os.path.isfile(chemin_local):
        logging.error("Fichier a imprimer introuvable : %s", chemin_local)
        return False

    logging.debug("Impression de %s sur '%s'...", chemin_local, printer_name)
    try:
        subprocess.run(
            [pdf_to_printer, chemin_local, printer_name],
            check=True,
            timeout=120,
        )
        logging.info("Impression reussie : %s", os.path.basename(chemin_local))
        return True
    except subprocess.CalledProcessError as e:
        logging.error("Erreur PDFtoPrinter (code %s) pour %s", e.returncode, chemin_local)
        return False
    except Exception as e:
        logging.error("Erreur impression %s : %s", chemin_local, e)
        return False


# =============================================================================
#  ARCHIVAGE LOCAL
# =============================================================================

def deplacer_fichier(source, destination):
    try:
        os.replace(source, destination)
        return True
    except OSError:
        try:
            shutil.move(source, destination)
            return True
        except Exception as e:
            logging.error("Echec deplacement %s -> %s : %s", source, destination, e)
            return False


def archiver_fichier(config, chemin_local, nom_fichier):
    if not config.get("archiver_fichier", True):
        return True

    archive_dir = config["archive_dir"]
    os.makedirs(archive_dir, exist_ok=True)

    base, ext = os.path.splitext(nom_fichier)
    chemin_archive = os.path.join(archive_dir, nom_fichier)
    if os.path.exists(chemin_archive):
        suffixe = datetime.now().strftime("%Y%m%d_%H%M%S")
        chemin_archive = os.path.join(archive_dir, "%s_%s%s" % (base, suffixe, ext))

    if deplacer_fichier(chemin_local, chemin_archive):
        logging.info("Fichier archive : %s", os.path.basename(chemin_archive))
        return True
    return False


# =============================================================================
#  TRAITEMENT D UN FICHIER
# =============================================================================

def traiter_fichier(config, sftp, nom_fichier, state):
    chemin_distant = posixpath.join(config["remote_path"], nom_fichier)
    chemin_local = os.path.join(config["local_path"], nom_fichier)
    confirmations = config.get("stability_confirmations", 2)

    logging.info("Traitement de : %s", nom_fichier)
    t_debut = time.time()

    # 1. Stabilite du fichier distant
    if not attendre_fichier_stable(
        sftp, chemin_distant,
        config["temps_attente"],
        config["retries_stabilite"],
        confirmations,
    ):
        logging.warning("Fichier %s non stable, report.", nom_fichier)
        return False

    # 2. Telechargement
    try:
        telecharger_fichier(sftp, chemin_distant, chemin_local)
        logging.info("Fichier telecharge : %s", nom_fichier)
    except Exception as e:
        logging.error("Echec telechargement %s : %s", nom_fichier, e)
        # Nettoyage du .downloading eventuel
        chemin_temp = chemin_local + ".downloading"
        if os.path.exists(chemin_temp):
            try:
                os.remove(chemin_temp)
            except OSError:
                pass
        return False

    # 3. Impression (optionnelle)
    time.sleep(config.get("sleep_before_print", 0))
    if not imprimer_fichier(config, chemin_local):
        logging.error("Impression echouee pour %s", nom_fichier)
        # On ne supprime PAS le fichier distant -> retry
        return False

    # 4. Archivage (optionnel)
    time.sleep(config.get("sleep_before_move", 0))
    if not archiver_fichier(config, chemin_local, nom_fichier):
        logging.error("Archivage echoue pour %s", nom_fichier)
        return False

    # 5. Suppression du fichier distant (uniquement si tout est OK)
    if config.get("supprimer_apres_traitement", True):
        try:
            sftp.remove(chemin_distant)
            logging.info("Fichier distant supprime : %s", nom_fichier)
        except Exception as e:
            logging.error("Echec suppression distante %s : %s", nom_fichier, e)
            return False

    # 6. Marquer comme traite
    state[nom_fichier] = time.time()

    duree = time.time() - t_debut
    logging.debug("Fichier %s traite en %.3f s.", nom_fichier, duree)
    return True


# =============================================================================
#  BOUCLE DE SURVEILLANCE
# =============================================================================

def surveiller(config):
    _lock_handle = None
    ssh = None
    sftp = None

    try:
        _lock_handle = verifier_instance_unique(config["lock_file"])
        setup_logger(config)

        # Verifier / creer les dossiers locaux
        os.makedirs(config["local_path"], exist_ok=True)
        os.makedirs(config["archive_dir"], exist_ok=True)

        # Charger l'etat
        state = charger_state(config["state_file"])
        purger_state(state, config.get("state_retention_days", 30))
        logging.debug("State charge : %s entree(s).", len(state))

        # Connexion SFTP
        logging.debug("Connexion SFTP initiale...")
        ssh, sftp = connecter_sftp(config)
        if sftp is None:
            logging.critical("Impossible de se connecter au SFTP. Arret.")
            sys.exit(1)

        extensions_valides = tuple(e.lower() for e in config["extensions_valides"])
        logging.debug("Extensions filtrees : %s", extensions_valides)

        numero_cycle = 0
        purge_state_tous_les_n = config.get("purge_state_every_n_cycles", 10000)

        while not _arreter:
            numero_cycle += 1
            logging.debug("--- Debut cycle #%s ---", numero_cycle)

            # Verification de la connexion
            if not connexion_sftp_active(ssh, sftp):
                logging.warning("Connexion SFTP perdue. Reconnexion...")
                try:
                    if sftp is not None:
                        sftp.close()
                except Exception:
                    pass
                try:
                    if ssh is not None:
                        ssh.close()
                except Exception:
                    pass

                ssh, sftp = connecter_sftp(config)
                if sftp is None:
                    logging.critical("Reconnexion SFTP impossible. Arret en erreur.")
                    raise RuntimeError("Reconnexion SFTP impossible")
            else:
                logging.debug("Verification connexion SFTP : OK")

            # Lister les fichiers distants
            try:
                tous_fichiers = sftp.listdir(config["remote_path"])
                logging.debug("Dossier distant scanne : %s entrees.", len(tous_fichiers))

                fichiers = []
                for f in tous_fichiers:
                    if not f.lower().endswith(extensions_valides):
                        continue
                    if f in state:
                        logging.debug("Fichier deja traite (state) : %s", f)
                        continue
                    fichiers.append(f)
                    logging.debug("Fichier retenu : %s", f)
            except Exception as e:
                logging.error("Erreur lecture dossier distant %s : %s", config["remote_path"], e)
                time.sleep(config["check_interval"])
                continue

            # Tri par nom pour traitement stable
            fichiers.sort()

            # Traitement sequentiel
            if fichiers:
                logging.info("%s fichier(s) a traiter : %s", len(fichiers), fichiers)
                for nom_fichier in fichiers:
                    if _arreter:
                        logging.debug("Arret demande, on stoppe.")
                        break
                    try:
                        traiter_fichier(config, sftp, nom_fichier, state)
                    except Exception as e:
                        logging.error(
                            "Erreur traitement %s : %s",
                            nom_fichier, e, exc_info=True,
                        )
                # Sauver le state apres chaque batch
                sauver_state(config["state_file"], state)
            else:
                logging.debug("Aucun fichier a traiter dans ce cycle.")

            # Purge periodique du state
            if purge_state_tous_les_n > 0 and numero_cycle % purge_state_tous_les_n == 0:
                logging.debug("Purge periodique du state...")
                purger_state(state, config.get("state_retention_days", 30))
                sauver_state(config["state_file"], state)

            logging.debug("--- Fin cycle #%s ---", numero_cycle)
            time.sleep(config["check_interval"])

    finally:
        logging.info("Arret du service...")
        try:
            if sftp is not None:
                sftp.close()
        except Exception:
            pass
        try:
            if ssh is not None:
                ssh.close()
        except Exception:
            pass
        try:
            if _lock_handle is not None:
                _lock_handle.close()
        except Exception:
            pass
        logging.info("Service arrete proprement.")


# =============================================================================
#  POINT D ENTREE
# =============================================================================

if __name__ == "__main__":
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
    else:
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "config.json"
        )

    try:
        config = charger_config(config_path)
    except Exception as e:
        print("ERREUR : chargement de la config impossible : %s" % e)
        sys.exit(1)

    try:
        valider_config(config)
    except ValueError as e:
        print("ERREUR : %s" % e)
        sys.exit(1)

    try:
        surveiller(config)
    except Exception as e:
        try:
            logging.critical("Erreur fatale : %s", e, exc_info=True)
        except Exception:
            print("ERREUR FATALE : %s" % e)
        sys.exit(1)