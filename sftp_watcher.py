import paramiko
import logging
import time
import os
import json
import shutil
import subprocess
from typing import Optional
from logging.handlers import TimedRotatingFileHandler
from concurrent.futures import ThreadPoolExecutor


# Fonction pour obtenir le répertoire du script
def obtenir_repertoire_script():
    return os.path.dirname(os.path.abspath(__file__))

# Charger les paramètres depuis le fichier JSON avec un chemin relatif
def charger_config(config_file="config.json"):
    # Chemin absolu relatif au répertoire du script
    script_dir = obtenir_repertoire_script()
    config_path = os.path.join(script_dir, config_file)
    
    with open(config_path, "r") as f:
        config = json.load(f)
    return config

# Fonction d'impression via PDFtoPrinter.exe avec chemin relatif
def imprimer_pdf_pdf2printer(printer_name: str, pdf_file_path: str) -> None:
    try:
        if not os.path.exists(pdf_file_path):
            logging.error(f"Le fichier PDF n'existe pas: {pdf_file_path}")
            return

        # Obtenir le chemin de PDFtoPrinter.exe de manière relative
        script_dir = obtenir_repertoire_script()
        pdf_to_printer_path = os.path.join(script_dir, "PDFtoPrinter", "PDFtoPrinter.exe")
        
        # Vérifier que le fichier PDFtoPrinter.exe existe
        if not os.path.exists(pdf_to_printer_path):
            logging.error(f"Le fichier PDFtoPrinter.exe n'existe pas à l'emplacement {pdf_to_printer_path}")
            return
        
        command = [pdf_to_printer_path, pdf_file_path, printer_name]
        subprocess.run(command, check=True)
        logging.info(f"Document {pdf_file_path} imprimé avec succès sur {printer_name}")
    except Exception as e:
        logging.error(f"Erreur d'impression avec PDFtoPrinter sur {printer_name}: {e}")


# Fonction pour vérifier si le fichier est complètement téléchargé
def est_fichier_complet(sftp: paramiko.SFTPClient, remote_path: str, fichier: str, temps_attente: int, retries: int) -> bool:
    """
    Vérifie si un fichier est complet en surveillant la taille du fichier.
    :param sftp: Client SFTP
    :param remote_path: Chemin distant du fichier
    :param fichier: Nom du fichier à vérifier
    :param temps_attente: Temps d'attente (en secondes) avant de vérifier à nouveau
    :param retries: Nombre de tentatives avant d'abandonner
    :return: True si le fichier est complet, False sinon
    """

    try:
        chemin_distant = os.path.join(remote_path, fichier)
        
        # Récupérer la taille initiale du fichier
        taille_initiale = sftp.stat(chemin_distant).st_size
        
        for _ in range(retries):
            time.sleep(temps_attente)  # Attente avant de vérifier à nouveau
            taille_actuelle = sftp.stat(chemin_distant).st_size
            if taille_initiale == taille_actuelle:
                logging.info(f"Le fichier {fichier} est complet.")
                return True
            else:
                logging.info(f"La taille du fichier {fichier} a changé. Nouvelle tentative...")
                taille_initiale = taille_actuelle  # Mise à jour de la taille initiale pour la prochaine vérification
        
        logging.warning(f"Le fichier {fichier} semble incomplet après plusieurs vérifications.")
        return False
    
    except Exception as e:
        logging.error(f"Erreur lors de la vérification du fichier {fichier}: {e}")
        return False




# Fonction pour établir une connexion SFTP avec tentative de reconnexion en cas d'échec
def reconnect_sftp(ssh: paramiko.SSHClient, hostname: str, port: int, username: str, password: str, private_key_path: Optional[str] = None, retries: int = 3) -> Optional[paramiko.SFTPClient]:
    for attempt in range(retries):
        try:
            
            # Charger les clés d'hôtes connues depuis known_hosts
            ssh.load_host_keys(config["known_hosts_file"])

            # Politique de clé manquante (Rejeter les clés inconnues)
            ssh.set_missing_host_key_policy(paramiko.RejectPolicy())

            # Connexion avec clé privée ou mot de passe
            if private_key_path:
                ssh.connect(hostname, port, username, key_filename=private_key_path)
                logging.info("Connexion SFTP réussie avec clé privée.")
            else:
                ssh.connect(hostname, port, username, password=password)
                logging.info("Connexion SFTP réussie avec mot de passe.")

            # Ouvrir le canal SFTP
            return ssh.open_sftp()

        except Exception as e:
            logging.error(f"Erreur de connexion SFTP (tentative {attempt+1}/{retries}): {e}")
            if attempt == retries - 1:
                logging.error("Toutes les tentatives de connexion ont échoué.")
                return None
            time.sleep(5)  # Attente avant la nouvelle tentative


# Configuration du logger avec rotation et archivage des logs
def setup_logger(activer_logs: bool, log_file: str, logs_archive_dir: str, log_level: str) -> None:
    log_dir = os.path.dirname(log_file)
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    if activer_logs:
        handler = TimedRotatingFileHandler(log_file, when="midnight", interval=1, backupCount=7)
        handler.suffix = "%Y-%m-%d.log"  # Format du suffixe des fichiers de log

        # Convertir le niveau de log en fonction du paramètre `log_level`
        log_level_dict = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL
        }
        level = log_level_dict.get(log_level.upper(), logging.INFO)   # Par défaut INFO si non spécifié

        logging.basicConfig(
            level=level,  # Niveau de log dynamique en fonction de la configuration
            handlers=[handler],
            format='%(asctime)s - %(levelname)s - %(message)s'  # Ajoute l'heure dans le format des logs
        )
        logging.info("Démarrage du script.")
    else:
        logging.disable(logging.CRITICAL)  # Désactive tous les logs si activer_logs est False


# Fonction pour archiver les logs dans un répertoire d'archive
def archiver_logs(log_file: str, archive_dir: str) -> None:
    log_dir = os.path.dirname(log_file)  # Répertoire contenant le fichier log actuel
    
    # Vérifier si le répertoire d'archive existe, sinon le créer
    if not os.path.exists(archive_dir):
        os.makedirs(archive_dir)

    try:
        # Déplacer les fichiers log (y compris les fichiers avec suffixe de date) vers l'archive
        for fichier_log in os.listdir(log_dir):
            # Filtrer les fichiers .log, y compris ceux avec suffixe de date
            if fichier_log.endswith(".log") and fichier_log != os.path.basename(log_file):
                archive_path = os.path.join(archive_dir, fichier_log)
                shutil.move(os.path.join(log_dir, fichier_log), archive_path)
                logging.info(f"Log déplacé dans l'archive : {archive_path}")
    except Exception as e:
        logging.error(f"Erreur lors de l'archivage des logs : {e}")



# Fonction pour télécharger et supprimer un fichier
def telecharger_et_supprimer_fichier(sftp: paramiko.SFTPClient, remote_path: str, local_path: str, fichier: str, deplacer_fichier: bool) -> None:
    try:
        chemin_distant = os.path.join(remote_path, fichier)
        chemin_local = os.path.join(local_path, fichier)

        if deplacer_fichier:
            logging.info(f"Téléchargement de {chemin_distant} vers {chemin_local}")
            sftp.get(chemin_distant, chemin_local)
            logging.info(f"Fichier téléchargé : {chemin_distant}")
            
            # Suppression du fichier sur le serveur
            sftp.remove(chemin_distant)
            logging.info(f"Fichier supprimé du serveur : {chemin_distant}")
    except Exception as e:
        logging.error(f"Erreur lors du téléchargement ou de la suppression du fichier {fichier}: {e}")


# Fonction pour traiter un fichier (téléchargement, impression, archivage)
def traiter_fichier(fichier: str, sftp: paramiko.SFTPClient, remote_path: str, local_path: str, printer_name: str, archive_dir: str, deplacer_fichier: bool, archiver_fichier: bool, imprimer_fichier: bool) -> None:
    try:
        chemin_distant = os.path.join(remote_path, fichier)
        chemin_local = os.path.join(local_path, fichier)

        # Vérification si le fichier est complet avant de le télécharger
        if not est_fichier_complet(sftp, remote_path, fichier,config["temps_attente"],config["retries"]):
            logging.error(f"Le fichier {fichier} n'est pas complet, saut du téléchargement.")
            return


        # Vérification de l'existence du répertoire local
        if deplacer_fichier and not os.path.exists(os.path.dirname(chemin_local)):
            os.makedirs(os.path.dirname(chemin_local), exist_ok=True)

        # Télécharger le fichier
        if deplacer_fichier:
            telecharger_et_supprimer_fichier(sftp, remote_path, local_path, fichier, deplacer_fichier)

        
        # Temporisation avant d'ouvrir le fichier
        time.sleep(config["sleep_before_print"])

        # Tentative d'impression via PDFtoPrinter
        if imprimer_fichier:
            imprimer_pdf_pdf2printer(printer_name, chemin_local)

        # Temporisation avant de déplacer le fichier dans les archives
        if archiver_fichier:
            time.sleep(config["sleep_before_move"])
            shutil.move(chemin_local, os.path.join(archive_dir, fichier))
            logging.info(f"Fichier archivé : {chemin_local}")

    except Exception as e:
        logging.error(f"Erreur d'impression ou d'extraction PDF pour {fichier}: {e}")


# Fonction pour surveiller les fichiers et traiter les nouveaux fichiers PDF
def surveiller_et_telecharger(config: dict) -> None:
    # Configuration du logger
    setup_logger(config["activer_logs"], config["log_file"], config["logs_archive_dir"], config["log_level"])
    
    # Connexion SFTP initiale
    ssh = paramiko.SSHClient()
    ssh.load_host_keys(config["known_hosts_file"])
    sftp = reconnect_sftp(ssh, config["hostname"], config["port"], config["username"], config["password"], config["private_key_path"], config["retries"])
    if sftp is None:
        logging.error("Échec de la connexion SFTP.")
        return

    try:
        # Tentative d'accès au répertoire distant
        logging.debug(f"Tentative d'accès au répertoire SFTP: {config['remote_path']}")
        fichiers_initiaux = set(sftp.listdir(config["remote_path"]))
        
        # Charger les extensions valides depuis config.json
        extensions_valides = tuple(config["extensions_valides"])  # Chargement des extensions valides à partir du JSON


        # Filtrage des fichiers PDF
        fichiers_pdf_initiaux = {fichier for fichier in fichiers_initiaux if fichier.lower().endswith(extensions_valides)}
        logging.debug(f"Fichiers PDF initiaux dans {config['remote_path']}: {fichiers_pdf_initiaux}")

        

        while True:
            # Vérification de la connexion SFTP avant chaque interaction
            if sftp.sock is None or sftp.sock.getpeername() is None:
                logging.warning("Connexion SFTP perdue, tentative de reconnexion...")
                
                # Tentatives de reconnexion avec un intervalle de 30 secondes
                reconnection_retries = 5  # Nombre de tentatives de reconnexion
                for attempt in range(reconnection_retries):
                    logging.info(f"Tentative de reconnexion SFTP {attempt + 1}/{reconnection_retries}...")
                    sftp = reconnect_sftp(ssh, config["hostname"], config["port"], config["username"], config["password"], config["private_key_path"], config["retries"])
                    
                    if sftp:
                        logging.info("Reconnexion SFTP réussie.")
                        break
                    else:
                        logging.error(f"Échec de la reconnexion SFTP (tentative {attempt + 1}/{reconnection_retries}).")
                        time.sleep(30)  # Attente de 30 secondes avant la prochaine tentative
                
                # Si la reconnexion échoue après toutes les tentatives, on quitte la boucle
                if not sftp:
                    logging.error("Échec de la reconnexion SFTP après plusieurs tentatives.")
                    break

            try:
                fichiers_actuels = set(sftp.listdir(config["remote_path"]))
                fichiers_pdf_actuels = {fichier for fichier in fichiers_actuels if fichier.lower().endswith(extensions_valides)}
                nouveaux_fichiers_pdf = fichiers_pdf_actuels - fichiers_pdf_initiaux
                
                if nouveaux_fichiers_pdf:
                    logging.info(f"Nouveaux fichiers PDF trouvés: {nouveaux_fichiers_pdf}")
                    
                    with ThreadPoolExecutor(max_workers=config["max_workers"]) as executor:
                        for fichier in nouveaux_fichiers_pdf:
                            executor.submit(traiter_fichier, fichier, sftp, config["remote_path"], config["local_path"], config["printer_name"], config["archive_dir"], config["deplacer_fichier"], config["archiver_fichier"], config["imprimer_fichier"])
                
                fichiers_pdf_initiaux = fichiers_pdf_actuels
                archiver_logs(config["log_file"], config["logs_archive_dir"])
            except Exception as e:
                logging.error(f"Erreur lors de la surveillance des fichiers: {e}")
            
            # Intervalle de vérification
            time.sleep(config["check_interval"])
    
    finally:
        logging.info("Fermeture de la connexion SFTP.")
        sftp.close()
        ssh.close()



if __name__ == "__main__":
    # Charger la configuration en utilisant un chemin relatif
    config = charger_config("config.json")
    
    # Appeler la fonction principale pour surveiller et traiter les fichiers
    surveiller_et_telecharger(config)
