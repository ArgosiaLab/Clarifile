# Fonctionnement de ClariFile

Ce document décrit le déroulement interne d'une session, les règles de classement et l'ensemble des protections.

## Déroulement d'une session

1. **Parcours.** Les dossiers indiqués sont parcourus avec élagage : un dossier protégé n'est jamais ouvert, ni lui ni son contenu. Les dossiers parents du point de départ sont eux aussi vérifiés, si bien que démarrer depuis `C:\Program Files\Logiciel\data` ou `/usr/share` ne contourne aucune protection.
2. **Examen des fichiers.** Chaque fichier passe des contrôles du moins coûteux au plus coûteux : nom, extension, catégorie, puis un seul appel système pour la taille et la date.
3. **Calcul de la destination.** Le chemin est construit selon la catégorie, puis vérifié : toute destination située hors du dossier choisi est refusée.
4. **Doublons.** Les fichiers au contenu identique sont repérés et laissés en place.
5. **Plan et simulation.** Le plan est affiché, puis une simulation est proposée.
6. **Exécution.** Les fichiers sont déplacés après confirmation explicite.
7. **Retour arrière.** Une annulation est proposée à la fin de la session.

## Règles de classement

| Catégorie     | Extensions                                        | Destination                              |
|---------------|---------------------------------------------------|------------------------------------------|
| Images        | jpg jpeg png gif bmp tiff webp heic raw           | `Photos/année/mois`                      |
| Vidéos        | mp4 avi mkv mov wmv flv mpeg mpg m4v              | `Videos/année/mois`                      |
| Audio         | mp3 wav flac aac ogg m4a wma                      | `Musique/artiste/album`                  |
| PDF           | pdf                                               | `Documents/PDF/année`                    |
| Texte         | doc docx odt rtf                                  | `Documents/Texte/année`                  |
| Tableurs      | xls xlsx ods csv                                  | `Documents/Tableurs/année`               |
| Présentations | ppt pptx odp                                      | `Documents/Presentations/année`          |
| Archives      | zip tar gz rar 7z tar.gz tar.bz2                  | `Archives/année`                         |
| Code          | py js ts html css php c cpp cs java sql sh        | `Code/langage`                           |

Pour les photos, la date de prise de vue EXIF est utilisée si elle existe. Dans tous les autres cas, c'est la date de dernière modification. Les fichiers audio sans tags sont rangés dans `Musique/Inconnu/Inconnu`.

Seuls les fichiers de code isolés sont rangés. Un fichier faisant partie d'un projet n'est jamais déplacé, car le projet entier est protégé.

Les extensions absentes de ce tableau ne sont jamais déplacées.

## Protections

### Dossiers jamais parcourus

| Protection                | Critère                                                                                     |
|---------------------------|---------------------------------------------------------------------------------------------|
| Système Windows           | Windows, Program Files, ProgramData, AppData, WindowsApps, corbeille, points de restauration |
| Système Linux             | /bin, /boot, /dev, /etc, /lib, /lib32, /lib64, /libx32, /opt, /proc, /root, /run, /sbin, /snap, /srv, /sys, /tmp, /usr, /var |
| Dossiers cachés           | Nom commençant par un point, ou attribut caché ou système sous Windows                      |
| Applications              | Présence d'une bibliothèque (`.dll`, `.so`, `.so.N`, `.dylib`, `.ocx`)                      |
| Launchers                 | Présence d'un manifeste (`.acf`, `.vdf`, `.manifest`, `.egstore`, `.appxmanifest`)          |
| Projets de code           | `.git`, `.hg`, `.svn`, `package.json`, `pyproject.toml`, `setup.py`, `requirements.txt`, `Pipfile`, `Cargo.toml`, `go.mod`, `pom.xml`, `build.gradle`, `CMakeLists.txt`, `Makefile`, `composer.json`, `Gemfile`, fichiers `.sln`, `.csproj`, `.vcxproj` et `.xcodeproj` |
| Dépendances régénérables  | `node_modules`, `__pycache__`, `site-packages`, `dist-packages`                             |
| Marqueur                  | Fichier `.clarifile-ignore` présent dans le dossier                                         |
| Exclusions personnelles   | Chemins ou noms de dossiers enregistrés en mode Avancé                                      |
| Destination               | Le dossier de destination n'est jamais réanalysé                                            |
| Liens                     | Liens symboliques et jonctions NTFS jamais suivis                                           |

La détection des applications et des projets n'est pas appliquée aux racines de disque ni au dossier personnel, qui ne sont jamais des applications.

### Fichiers jamais déplacés

- Exécutables et scripts système : `.exe`, `.msi`, `.appimage`, `.bat`, `.cmd`, `.ps1`, `.vbs`, `.reg`
- Bibliothèques : `.dll`, `.so`, `.dylib`, `.sys`
- Raccourcis : `.lnk`, `.desktop`, `.url`
- Configurations et bases de données : `.ini`, `.cfg`, `.conf`, `.config`, `.dat`, `.db`, `.sqlite`
- Images disque : `.iso`, `.img`, `.vhd`, `.vhdx`, `.vmdk`, `.qcow2`
- Fichiers cachés, fichiers vides, liens symboliques
- Le script ClariFile lui-même

### Destination

Le dossier de destination est refusé s'il est identique à un dossier analysé, ou s'il se trouve dans un emplacement protégé (dossier système, dossier caché, application, projet, `/tmp`).

Les noms de dossiers tirés des métadonnées (artiste, album) viennent du fichier lui-même et ne sont donc pas fiables. Ils sont nettoyés avant usage : séparateurs, caractères interdits, `..` et noms réservés de Windows (`CON`, `NUL`, `COM1`...) sont neutralisés. Un tag audio piégé ne peut pas faire sortir un fichier du dossier de destination.

## Doublons

La recherche procède en trois filtres, du moins coûteux au plus coûteux :

1. même taille, sans aucune lecture disque ;
2. même empreinte des 64 premiers Ko ;
3. même empreinte du fichier entier.

Les empreintes utilisent BLAKE2b, résistant aux collisions. Toutes les copies d'un même contenu restent en place : le choix de la copie à conserver revient à un outil de déduplication.

## Orphelins

Le rapport des orphelins signale les fichiers à vérifier à la main :

- fichiers vides : non déplacés ;
- fichiers sans extension : non déplacés ;
- noms qui semblent aléatoires ou peu significatifs : signalés, mais rangés normalement.

Les noms composés uniquement d'une date et d'une heure, typiques des appareils photo et des téléphones (`20240812_143055.jpg`), sont considérés comme normaux.

## Mode Propositions

1. Le mode 3 génère un fichier texte listant chaque déplacement prévu. Aucun fichier n'est déplacé.
2. Pour valider un déplacement, ajouter un espace puis `OK` à la fin de sa ligne `DESTINATION PROPOSEE`. La destination peut être modifiée, à condition de rester dans le dossier de destination.
3. Relancer le mode 3 et choisir l'option 1 pour exécuter les propositions validées.

Le fichier étant modifiable à la main, chaque ligne validée est contrôlée de nouveau avec les mêmes protections que lors de l'analyse. Une source protégée, une destination hors du dossier choisi ou un chemin relatif sont refusés et listés à l'écran.

## Retour arrière

À la fin d'une session, taper `annuler` remet chaque fichier à son emplacement d'origine, dans l'ordre inverse des déplacements. Les sous-dossiers devenus vides dans la destination sont supprimés. Si un fichier a été recréé entre-temps à l'emplacement d'origine, il n'est jamais écrasé : le déplacement correspondant est signalé en échec dans le journal.

Une interruption au clavier (Ctrl+C) pendant les déplacements conserve la liste des opérations déjà faites, ce qui permet toujours le retour arrière.

## Historique

L'historique conserve une ligne par session. Sa consultation peut être protégée par un mot de passe, saisi sans affichage et stocké sous forme de hachage PBKDF2-SHA256 salé. Il s'agit d'un verrou de consultation dans le menu : le fichier d'historique reste un texte lisible par toute personne ayant accès au dossier de travail.

## Fichiers de travail

| Fichier                        | Contenu                                         |
|--------------------------------|-------------------------------------------------|
| `clarifile_log.txt`            | Journal détaillé de chaque déplacement          |
| `clarifile_historique.txt`     | Une ligne par session                           |
| `clarifile_historique.key`     | Hachage du mot de passe de l'historique         |
| `clarifile_propositions.txt`   | Propositions du mode 3                          |
| `clarifile_orphelins.txt`      | Rapport des fichiers suspects                   |
| `clarifile_exclusions.txt`     | Exclusions personnelles, un chemin ou un nom par ligne |

Ils sont enregistrés dans `%APPDATA%\ClariFile` sous Windows et dans `~/.local/share/clarifile` sous Linux (ou dans `$XDG_DATA_HOME/clarifile` si cette variable est définie). Ils ne se mêlent donc jamais aux fichiers analysés ni au code source.
