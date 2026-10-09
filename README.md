# FTP Watcher

> Service Python qui surveille un répertoire distant SFTP et télécharge automatiquement les fichiers, avec impression et archivage local optionnels.

[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)]()

## Sommaire

- [Fonctionnalités](#fonctionnalités)
- [Architecture](#architecture)
- [Installation](#installation)
- [Configuration](#configuration)
- [Déploiement en service Windows](#déploiement-en-service-windows)
- [Comportement en cas d'erreur](#comportement-en-cas-derreur)
- [Dépannage](#dépannage)
- [Licence](#licence)

## Fonctionnalités

- **Surveillance continue** d'un répertoire distant SFTP
- **Téléchargement automatique** des nouveaux fichiers
- **Impression optionnelle** via PDFtoPrinter
- **Archivage local** des fichiers traités
- **Suppression distante** après traitement réussi
- **Suivi persistant** : les fichiers déjà traités ne sont pas rejoués (fichier `state.json`)
- **Verrou mono-instance** : impossible de lancer deux instances en parallèle
- **Détection de fin d'écriture** : attend que le fichier distant soit stable
- **Reconnexion automatique** avec keepalive SSH
- **Logs rotatifs** avec mode DEBUG activable

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Service (NSSM)                                             │
│  - Verrou mono-instance                                     │
│  - Une connexion SFTP avec keepalive                        │
│  - Traitement sequentiel                                    │
│  - State persistant (state.json)                            │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼  Pour chaque fichier distant
┌─────────────────────────────────────────────────────────────┐
│  1. Attendre stabilite (taille + mtime + confirmations)     │
│  2. Telecharger  remote  ->  local.downloading -> local     │
│  3. Imprimer (optionnel, via PDFtoPrinter)                  │
│  4. Archiver localement                                     │
│  5. Supprimer le fichier distant                            │
│  6. Marquer comme traite dans state.json                    │
└─────────────────────────────────────────────────────────────┘
```

## Installation

### Prérequis

- Python 3.9+
- [PDFtoPrinter](http://www.columbia.edu/~em36/pdftoprinter.html) (si l'impression est activée)
- [NSSM](https://nssm.cc/) (pour l'installation en service Windows)

### 1. Cloner le projet

```bash
git clone https://github.com/Seydr/FTP_Watcher.git
cd FTP_Watcher
```

### 2. Installer les dépendances

```bash
pip install -r requirements.txt
```

### 3. Générer le `known_hosts`

```bash
ssh-keyscan -t ecdsa sftp.example.com > known_hosts
```

### 4. Placer PDFtoPrinter (optionnel)

Créer un dossier `PDFtoPrinter/` à la racine du projet et y placer `PDFtoPrinter.exe`.

### 5. Configurer

```bash
cp config.example.json config.json
```

Éditer `config.json` avec vos valeurs (identifiants SFTP, chemins locaux, imprimante, etc.).

### 6. Test manuel

```bash
python sftp_watcher.py config.json
```

Déposez un fichier correspondant au filtre sur le serveur SFTP distant et vérifiez les logs.

## Configuration

### SFTP

| Clé | Type | Description |
| :--- | :--- | :--- |
| `hostname` | string | Serveur SFTP |
| `port` | int | Port (défaut: 22) |
| `username` | string | Utilisateur |
| `password` | string | Mot de passe (si pas de clé privée) |
| `private_key_path` | string ou null | Chemin vers la clé privée SSH |
| `known_hosts_file` | string | Fichier known_hosts |
| `remote_path` | string | Répertoire distant à surveiller |
| `retries` | int | Nombre de tentatives de connexion |

### Traitement

| Clé | Type | Description |
| :--- | :--- | :--- |
| `local_path` | string | Répertoire local de téléchargement |
| `archive_dir` | string | Répertoire d'archivage après traitement |
| `extensions_valides` | array | Extensions acceptées (ex: `[".pdf", ".csv"]`) |
| `supprimer_apres_traitement` | bool | Supprime le fichier distant après succès |
| `archiver_fichier` | bool | Déplace le fichier local vers `archive_dir` |
| `imprimer_fichier` | bool | Imprime le fichier via PDFtoPrinter |

### Impression

| Clé | Type | Description |
| :--- | :--- | :--- |
| `printer_name` | string | Nom de l'imprimante cible |
| `pdf_to_printer_path` | string | Chemin complet vers `PDFtoPrinter.exe` |

### Temporisations

| Clé | Type | Description |
| :--- | :--- | :--- |
| `check_interval` | number | Intervalle de scan en secondes |
| `temps_attente` | number | Délai entre 2 vérifications de stabilité |
| `retries_stabilite` | int | Nombre max de vérifications |
| `stability_confirmations` | int | Confirmations consécutives requises |
| `sleep_before_print` | number | Délai avant impression |
| `sleep_before_move` | number | Délai avant archivage |

### Logs

| Clé | Type | Description |
| :--- | :--- | :--- |
| `activer_logs` | bool | Active ou non les logs |
| `log_file` | string | Chemin du fichier de log |
| `log_level` | string | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `log_backup_count` | int | Nombre de jours d'historique |

### État et verrouillage

| Clé | Type | Description |
| :--- | :--- | :--- |
| `lock_file` | string | Fichier de verrou mono-instance |
| `state_file` | string | Fichier de suivi des fichiers traités |
| `state_retention_days` | int | Durée de conservation des entrées du state |
| `purge_state_every_n_cycles` | int | Fréquence de purge du state |

## Déploiement en service Windows

Une fois le test manuel validé, installez le service avec NSSM :

```cmd
nssm install FTPWatcher "C:\Python311\python.exe" "C:\Path\sftp_watcher.py" "C:\Path\config.json"
nssm set FTPWatcher AppDirectory "C:\Path"
nssm set FTPWatcher AppStdout "C:\Path\logs\stdout.log"
nssm set FTPWatcher AppStderr "C:\Path\logs\stderr.log"
nssm set FTPWatcher AppRotateFiles 1
nssm set FTPWatcher AppRotateOnline 1
nssm set FTPWatcher AppRotateBytes 10485760
nssm set FTPWatcher AppExit Default Restart
nssm set FTPWatcher AppRestartDelay 5000
nssm set FTPWatcher Start SERVICE_AUTO_START
nssm start FTPWatcher
```

### Commandes utiles

| Action | Commande |
| :--- | :--- |
| Démarrer | `nssm start FTPWatcher` |
| Arrêter | `nssm stop FTPWatcher` |
| Redémarrer | `nssm restart FTPWatcher` |
| Voir le statut | `nssm status FTPWatcher` |
| Éditer la config | `nssm edit FTPWatcher` |
| Supprimer | `nssm remove FTPWatcher confirm` |

## Comportement en cas d'erreur

| Situation | Comportement |
| :--- | :--- |
| Fichier distant en cours d'écriture | Attend la stabilité (max ~8 s) |
| Coupure réseau pendant téléchargement | Le `.downloading` est supprimé, retry au prochain cycle |
| Échec d'impression | Le fichier distant n'est **pas** supprimé → retry |
| Échec d'archivage | Le fichier distant n'est **pas** supprimé → retry |
| Coupure SFTP prolongée | Reconnexion auto (3 tentatives × 5 s) |
| Échec définitif de reconnexion | Arrêt en erreur → NSSM redémarre |
| Crash après suppression distante | Le fichier est marqué dans `state.json` → pas de retry |

## Dépannage

### Le service ne démarre pas

Vérifier que `config.json` est valide et que le `known_hosts_file` existe. Consulter `logs\stdout.log` et `logs\stderr.log`.

### Les fichiers ne sont pas téléchargés

Vérifier dans les logs :
- La connexion SFTP est-elle réussie ?
- Le filtre `extensions_valides` correspond-il bien aux fichiers déposés ?
- Les fichiers sont-ils en `state.json` (déjà traités) ?

### Un fichier est marqué comme traité mais n'a pas été imprimé

Vérifier que le fichier `state.json` ne contient pas une entrée erronée. Si besoin, éditer le fichier pour retirer l'entrée.

### Activer le mode DEBUG

Dans `config.json` :
```json
"log_level": "DEBUG"
```

Puis redémarrer le service. Attention : le mode DEBUG génère beaucoup de volume.

## Licence

MIT — voir le fichier [LICENSE](LICENSE).