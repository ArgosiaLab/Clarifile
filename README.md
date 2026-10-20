# ClariFile

Range automatiquement les fichiers personnels en vrac (photos, vidéos, musique, documents, archives, code) dans une arborescence claire, classée par type et par date, sans jamais toucher au système, aux logiciels ni aux jeux.

## Fonctionnalités

- Rangement par type et par date : `Photos/2019/07-Juillet`, `Documents/PDF/2024`, `Musique/Artiste/Album`
- Date de prise de vue lue dans les métadonnées EXIF des photos
- Artiste et album lus dans les tags des fichiers audio
- Simulation complète avant tout déplacement
- Retour arrière en fin de session : chaque fichier revient à sa place d'origine
- Détection des doublons, laissés en place
- Rapport des fichiers suspects (vides, sans extension, nom aléatoire)
- Mode Propositions : liste éditable des déplacements, validée ligne par ligne
- Protection automatique des dossiers système, des configurations, des logiciels, des jeux et des projets de code
- Aucune suppression de fichier, uniquement des déplacements
- Conçu pour Windows et Linux (testé sous Linux)

## Prérequis

- Python 3.8 ou version supérieure
- Dépendances optionnelles listées dans `requirements.txt`

Sans les dépendances optionnelles, ClariFile fonctionne et se base sur la date de modification des fichiers.

## Installation

Télécharger le contenu du dépôt, puis installer les dépendances optionnelles.

Sous Windows :

```bash
py -m pip install -r requirements.txt
```

Sous Debian, Ubuntu ou dérivés :

```bash
sudo apt install python3-pil python3-mutagen
```

Sous une autre distribution Linux, dans un environnement virtuel :

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

## Utilisation

Sous Windows :

```bash
py clarifile.py
```

Sous Linux :

```bash
python3 clarifile.py
```

Le script est entièrement interactif. Le menu principal propose :

| Choix | Mode          | Usage                                                           |
|-------|---------------|-----------------------------------------------------------------|
| 1     | Simple        | Tous les types de fichiers, réglages par défaut                 |
| 2     | Avancé        | Choix des catégories et des dossiers à exclure                  |
| 3     | Propositions  | Génère une liste de déplacements à valider, puis l'exécute      |
| H     | Historique    | Consulte l'historique des sessions                              |
| Q     | Quitter       |                                                                 |

Déroulement type en mode Simple :

1. Indiquer le ou les dossiers à ranger, par exemple le dossier Téléchargements.
2. Indiquer le dossier de destination, ou valider le dossier proposé par défaut.
3. Lancer une simulation pour vérifier ce qui sera déplacé.
4. Confirmer l'exécution.
5. Taper `annuler` à la fin pour tout remettre en place si le résultat ne convient pas.

Plusieurs dossiers peuvent être analysés en une fois en les séparant par un point-virgule.

## Arborescence produite

```text
ClariFile_Organisation/
  Photos/2024/08-Aout/
  Videos/2023/12-Decembre/
  Musique/Artiste/Album/
  Documents/PDF/2024/
  Documents/Texte/2024/
  Documents/Tableurs/2024/
  Documents/Presentations/2024/
  Archives/2024/
  Code/Python/
```

Un fichier qui porte le même nom qu'un fichier déjà présent est renommé avec un suffixe (`photo_2.jpg`) : rien n'est jamais écrasé.

## Sécurité

ClariFile ne parcourt jamais :

- les dossiers système (Windows, Program Files, AppData, ProgramData, /usr, /etc, /var, /tmp...) ;
- les dossiers cachés, qui contiennent les configurations des logiciels ;
- les dossiers d'application, reconnus automatiquement à leur contenu (bibliothèques `.dll`, `.so`, manifestes) : logiciels, jeux et launchers sont protégés sans avoir besoin d'être nommés ;
- les projets de code (`.git`, `package.json`, `pyproject.toml`, `Makefile`...), pour ne jamais disperser leurs fichiers ;
- les liens symboliques et jonctions.

Les exécutables, raccourcis, fichiers de configuration et images disque ne sont jamais déplacés.

Pour protéger un dossier précis, deux possibilités :

- y placer un fichier vide nommé `.clarifile-ignore` ;
- l'ajouter à la liste d'exclusions proposée par le mode Avancé.

Le détail des protections est décrit dans [FONCTIONNEMENT.md](FONCTIONNEMENT.md).

## Fichiers de travail

Journal, historique, propositions, rapport des orphelins et exclusions sont enregistrés hors du dossier du script :

| Système | Emplacement                  |
|---------|------------------------------|
| Windows | `%APPDATA%\ClariFile`        |
| Linux   | `~/.local/share/clarifile`   |

## Structure du projet

```text
clarifile.py        script complet
requirements.txt    dépendances optionnelles
FONCTIONNEMENT.md   fonctionnement détaillé et protections
LICENSE             licence MIT
```

## Contribuer

Ouvrir une issue avant toute modification importante, puis proposer une pull request. Toute contribution doit conserver le principe de base : ne jamais supprimer un fichier et ne jamais entrer dans un dossier protégé.

## Licence

Distribué sous licence MIT. Voir le fichier [LICENSE](LICENSE).
