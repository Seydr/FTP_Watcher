# SFTP_Watcher

# Import des modules
pip install paramiko logging subprocess shutil concurrent  

## Description du Script
Ce script a pour objectif de surveiller un répertoire distant via SFTP, de télécharger, d'imprimer et d'archiver des fichiers PDF automatiquement. Il fonctionne en mode continu, en vérifiant régulièrement l'existence de nouveaux fichiers PDF dans le répertoire distant spécifié. Lorsqu'un nouveau fichier PDF est détecté, il est traité selon une série d'actions configurables, incluant son téléchargement, son impression et son archivage local.  
Le script utilise des threads pour gérer plusieurs fichiers simultanément, permettant ainsi d'optimiser les performances lors du traitement de plusieurs fichiers.  
# Fonctionnalités principales  
## Surveillance SFTP :
Le script se connecte à un serveur SFTP en utilisant des informations d'identification telles qu'un mot de passe ou une clé privée. Il vérifie en permanence le répertoire distant à la recherche de nouveaux fichiers PDF.  
La connexion SFTP peut être rétablie en cas de déconnexion, et plusieurs tentatives sont effectuées pour garantir une connexion fiable.  
## Vérification de la complétude des fichiers :  
Avant de télécharger un fichier, le script vérifie que le fichier est complet en surveillant sa taille. Si la taille du fichier reste inchangée sur plusieurs cycles de vérification, il est considéré comme complet et prêt à être téléchargé.  
## Téléchargement et suppression de fichiers :
Une fois le fichier PDF complet, il est téléchargé depuis le serveur SFTP vers un répertoire local. Après cela, le fichier est supprimé du serveur distant pour éviter les doublons.  
## Impression des fichiers PDF :  
Après le téléchargement, le fichier PDF peut être envoyé à une imprimante configurée via l'outil PDFtoPrinter.exe, qui permet d'imprimer des fichiers PDF sans ouvrir une application dédiée. La temporisation avant l'impression peut être configurée dans le fichier de configuration.  
## Archivage des fichiers :
Le fichier PDF téléchargé peut être déplacé dans un répertoire d'archive après avoir été imprimé. La temporisation avant le déplacement peut également être configurée pour garantir que le processus d'impression est terminé avant de déplacer le fichier.  
## Archivage des logs :
Les logs du script sont archivés chaque jour à l'aide d'un mécanisme de rotation de fichiers. Les logs anciens peuvent être déplacés vers un répertoire d'archive pour conserver l'historique des exécutions du script.  
Exécution en mode multithread :  
Le script utilise un ThreadPoolExecutor pour traiter plusieurs fichiers simultanément, ce qui améliore la performance lors du traitement de nombreux fichiers. Cela permet d'exécuter des tâches telles que l'impression et l'archivage sans bloquer le traitement des autres fichiers.  
## Reconnexion Automatique SFTP :
En cas de perte de la connexion SFTP, le script tente automatiquement de se reconnecter pendant un nombre défini de tentatives. (5 fois tout les 30 secondes)  
  
# Configuration
Le script est configuré à l'aide d'un fichier config.json qui contient tous les paramètres nécessaires à son exécution. Les principaux paramètres configurables sont :  
## Connexion SFTP :
hostname : Adresse du serveur SFTP.  
port : Port utilisé pour la connexion (par défaut 22).  
username : Nom d'utilisateur pour la connexion.  
password : Mot de passe pour la connexion (ou private_key_path pour utiliser une clé privée).  
private_key_path : Chemin vers le fichier de clé privée (optionnel si un mot de passe est utilisé).  
remote_path : Chemin du répertoire à surveiller sur le serveur SFTP.  
local_path : Répertoire local où les fichiers seront téléchargés.  
## Impression et archivage :
printer_name : Nom de l'imprimante pour l'impression des fichiers PDF.  
archive_dir : Répertoire d'archive pour déplacer les fichiers après leur traitement.  
deplacer_fichier : Si True, les fichiers seront supprimés du serveur après téléchargement.  
archiver_fichier : Si True, les fichiers seront archivés après traitement.  
imprimer_fichier : Si True, les fichiers seront imprimés avant l'archivage.  
## Temporisation :
sleep_before_print : Temps d'attente (en secondes) avant de lancer l'impression d'un fichier.  
sleep_before_move : Temps d'attente (en secondes) avant de déplacer un fichier vers le répertoire d'archive.  
## Logs :
activer_logs : Si True, l'enregistrement des logs est activé.  
log_file : Chemin du fichier de log.  
logs_archive_dir : Répertoire où les logs seront archivés.  
log_level : Niveau de détail des logs (par exemple, INFO, DEBUG, ERROR).  
## Autres :
max_workers : Nombre maximum de threads pour traiter les fichiers en parallèle.  
check_interval : Intervalle (en secondes) entre chaque vérification des nouveaux fichiers sur le serveur.  
  
# Fonctionnement
Le script se lance et charge la configuration à partir du fichier config.json.  
Il établit une connexion SFTP avec les informations d'identification fournies.  
Le répertoire distant est surveillé à la recherche de nouveaux fichiers PDF. 
Lorsqu'un fichier est trouvé, il est vérifié pour s'assurer qu'il est complet.  
Le fichier est téléchargé, imprimé (si configuré) et archivé (si configuré).  
Les logs de l'exécution du script sont enregistrés et archivés de manière régulière.  
  
# Conclusion
Ce script permet d'automatiser le processus de surveillance, de téléchargement, d'impression et d'archivage des fichiers PDF via une connexion SFTP. Grâce à sa configuration flexible et son fonctionnement en mode multithread, il est parfaitement adapté pour gérer un grand nombre de fichiers PDF de manière efficace et sans intervention manuelle.  
  
## Configuration de l'impression
Utilisation de PDFtoPrinter pour imprimer
.\PDFtoPrinter\PDFtoPrinter.exe

## Générer la clé SSH pour se connecter 

ssh-keygen  <-- Pour creer les dossier  
ssh-keyscan -t ecdsa sftpserveur.com >>  ~/.ssh/known_hosts  

Se rendre dans C:\Users\usename\.ssh\  
Ouvrir le fichier "known_hosts" et changer l'encodage de UTF6 à UTF8. Enregistrer  
Le déplacer dans : .\sFTP_Watcher\  
