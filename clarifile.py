#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ClariFile - Organisation automatique de fichiers par type et par date

DESCRIPTION
  ClariFile parcourt un ou plusieurs dossiers et range les fichiers
  personnels (photos, videos, musique, documents, tableurs, presentations,
  archives, code) dans une arborescence claire. Les fichiers sont DEPLACES,
  jamais supprimes. Chaque execution peut etre simulee avant, puis annulee
  apres coup.

COMPATIBILITE
  Windows et Linux, Python 3.8 ou plus recent.

DEPENDANCES OPTIONNELLES
  Pillow   : date de prise de vue des photos (EXIF)
  mutagen  : artiste et album des fichiers audio
  Sans elles, le script fonctionne et se base sur la date de modification.
  Installation : pip install Pillow mutagen
  Sous Debian/Ubuntu : sudo apt install python3-pil python3-mutagen

UTILISATION
  python3 clarifile.py   (Linux)
  py clarifile.py        (Windows)
  Le script est entierement interactif. Trois modes sont proposes :
    1. Simple       : tous les types de fichiers, reglages par defaut.
    2. Avance       : choix des categories et exclusions supplementaires.
    3. Propositions : ecrit un fichier texte listant chaque deplacement prevu.
                      Les lignes validees par OK sont executees au lancement
                      suivant du mode 3.
  Une simulation est toujours proposee avant tout deplacement, et un retour
  arriere (rollback) est propose a la fin.

CE QUI N'EST JAMAIS TOUCHE
  - Les dossiers systeme (Windows, Program Files, AppData, /usr, /etc...).
  - Les dossiers caches (nom commencant par un point, ou attribut cache
    ou systeme sous Windows) : configurations des logiciels, ~/.config...
  - Les dossiers d'application, detectes automatiquement : presence de
    bibliotheques (.dll, .so, .dylib) ou de manifestes de logiciels.
    Jeux, launchers et logiciels portables sont ainsi proteges sans
    avoir besoin de les nommer.
  - Les projets de code (.git, package.json, pyproject.toml, Makefile...),
    pour ne jamais casser un projet en dispersant ses fichiers.
  - Tout dossier contenant un fichier vide nomme .clarifile-ignore.
  - Les dossiers listes dans le fichier d'exclusions (mode Avance).
  - Les liens symboliques et les executables.

FICHIERS DE TRAVAIL
  Journal, historique, propositions et exclusions sont ranges dans :
    Windows : %APPDATA%\\ClariFile
    Linux   : ~/.local/share/clarifile
  Ils ne se melangent donc jamais aux fichiers analyses ni au code source.
"""

from __future__ import annotations

import os
import sys
import re
import shutil
import hashlib
import hmac
import getpass
import ctypes
from datetime import datetime
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
# VERIFICATION DES DEPENDANCES OPTIONNELLES
# ─────────────────────────────────────────────────────────────────────────────

PILLOW_OK = False
MUTAGEN_OK = False

try:
    from PIL import Image
    from PIL.ExifTags import TAGS
    import logging
    logging.getLogger("PIL").setLevel(logging.CRITICAL)
    PILLOW_OK = True
except ImportError:
    pass

try:
    import mutagen
    from mutagen.easyid3 import EasyID3
    from mutagen.flac import FLAC
    from mutagen.mp4 import MP4
    from mutagen.oggvorbis import OggVorbis
    MUTAGEN_OK = True
except ImportError:
    pass


def afficher_etat_dependances():
    """Affiche l'etat de chaque dependance optionnelle au demarrage."""
    deps = [
        ("Pillow",  PILLOW_OK,  "Pillow",  "python3-pil",     "date de prise de vue des photos"),
        ("mutagen", MUTAGEN_OK, "mutagen", "python3-mutagen", "artiste et album des fichiers audio"),
    ]
    manquantes = [d for d in deps if not d[1]]
    if not manquantes:
        return
    print("")
    print("--- Dependances optionnelles manquantes ---")
    for nom, _, paquet_pip, paquet_apt, usage in manquantes:
        print(f"  [!] {nom:<8} absent : {usage}")
        print(f"      pip install {paquet_pip}   (Debian/Ubuntu : sudo apt install {paquet_apt})")
    print("  Le script continue et utilise la date de modification a la place.")
    print("")


# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────────────────────────────────────

VERSION = "1.1.0"
NOM_LOG           = "clarifile_log.txt"
NOM_ORPHELINS     = "clarifile_orphelins.txt"
NOM_PROPOSITIONS  = "clarifile_propositions.txt"
NOM_HISTORIQUE    = "clarifile_historique.txt"
NOM_HISTORIQUE_CLE= "clarifile_historique.key"
NOM_EXCLUSIONS    = "clarifile_exclusions.txt"

# Fichier marqueur : tout dossier qui le contient est ignore avec son contenu
NOM_MARQUEUR_IGNORE = ".clarifile-ignore"

# Noms de dossiers jamais parcourus, ou qu'ils se trouvent (insensible a la casse)
DOSSIERS_INTERDITS = {
    # Windows
    "windows", "program files", "program files (x86)", "programdata",
    "appdata", "windowsapps", "system32", "syswow64", "winsxs",
    "$recycle.bin", "system volume information", "recovery", "perflogs",
    "msocache", "config.msi", "$windows.~bt", "$windows.~ws",
    "$sysreset", "$winreagent", "boot",
    # Linux
    "lost+found",
    # Dependances regenerables des outils de developpement
    "node_modules", "__pycache__", "site-packages", "dist-packages",
}

# Dossiers racine systeme sous Linux (compares en chemin absolu)
RACINES_SYSTEME_UNIX = {
    "/bin", "/boot", "/dev", "/etc", "/lib", "/lib32", "/lib64", "/libx32",
    "/opt", "/proc", "/root", "/run", "/sbin", "/snap", "/srv", "/sys",
    "/tmp", "/usr", "/var",
}

# Un dossier contenant au moins un de ces fichiers est un dossier
# d'application (logiciel, jeu, launcher) : il est ignore en entier.
# (.sys est exclu : la racine C:\ contient pagefile.sys et hiberfil.sys)
EXTENSIONS_BIBLIOTHEQUE = {".dll", ".so", ".dylib", ".ocx"}
EXTENSIONS_MANIFESTE    = {".acf", ".vdf", ".manifest", ".egstore", ".appxmanifest"}

# Un dossier contenant un de ces elements est la racine d'un projet de code
MARQUEURS_PROJET = {
    ".git", ".hg", ".svn", "package.json", "pyproject.toml", "setup.py",
    "requirements.txt", "pipfile", "cargo.toml", "go.mod", "pom.xml",
    "build.gradle", "cmakelists.txt", "makefile", "composer.json",
    "gemfile",
}
EXTENSIONS_PROJET = {".sln", ".csproj", ".vcxproj", ".xcodeproj"}

# Extensions jamais deplacees, meme si un dossier n'a pas ete reconnu :
# executables, raccourcis, configurations, images disque.
EXTENSIONS_INTERDITES = {
    ".exe", ".dll", ".sys", ".so", ".dylib", ".msi", ".appimage",
    ".bat", ".cmd", ".ps1", ".vbs", ".reg",
    ".lnk", ".desktop", ".url",
    ".ini", ".cfg", ".conf", ".config", ".dat", ".db", ".sqlite",
    ".iso", ".img", ".vhd", ".vhdx", ".vmdk", ".qcow2",
}

# Noms reserves par Windows, interdits comme nom de fichier ou de dossier
NOMS_RESERVES_WINDOWS = (
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)

# Categories et leurs extensions
CATEGORIES = {
    "images":        {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff",
                      ".webp", ".heic", ".raw"},
    "videos":        {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv",
                      ".mpeg", ".mpg", ".m4v"},
    "audio":         {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"},
    "documents_pdf": {".pdf"},
    "documents_word":{".doc", ".docx", ".odt", ".rtf"},
    "tableurs":      {".xls", ".xlsx", ".ods", ".csv"},
    "presentations": {".ppt", ".pptx", ".odp"},
    "archives":      {".zip", ".tar", ".gz", ".rar", ".7z",
                      ".tar.gz", ".tar.bz2"},
    "code":          {".py", ".js", ".ts", ".html", ".css", ".php",
                      ".c", ".cpp", ".cs", ".java", ".sql", ".sh"},
}

# Mapping extension -> sous-dossier Code
LANGAGE_CODE = {
    ".py":   "Python",
    ".js":   "JavaScript",
    ".ts":   "TypeScript",
    ".html": "HTML",
    ".css":  "CSS",
    ".php":  "PHP",
    ".c":    "C",
    ".cpp":  "CPP",
    ".cs":   "CSharp",
    ".java": "Java",
    ".sql":  "SQL",
    ".sh":   "Shell",
}

# Noms des mois en francais
MOIS_FR = {
    1: "01-Janvier", 2: "02-Fevrier", 3: "03-Mars",
    4: "04-Avril",   5: "05-Mai",      6: "06-Juin",
    7: "07-Juillet", 8: "08-Aout",     9: "09-Septembre",
    10: "10-Octobre",11: "11-Novembre",12: "12-Decembre",
}

# Patterns detectant un nom "aleatoire" (orphelin potentiel)
PATTERN_ALEATOIRE = re.compile(
    r"^[a-z0-9]{1,3}$|^[0-9]+$|^[qwerty]{5,}|^[asdf]{5,}|^[zxcv]{5,}",
    re.IGNORECASE
)


# ─────────────────────────────────────────────────────────────────────────────
# UTILITAIRES GENERAUX
# ─────────────────────────────────────────────────────────────────────────────

EST_WINDOWS = sys.platform == "win32"


def normaliser_chemin(chemin: str) -> Path:
    """
    Nettoie une saisie utilisateur et retourne un chemin absolu.
    Gere les guillemets (glisser-deposer), le ~ et la lettre de lecteur seule.
    """
    chemin = chemin.strip().strip('"').strip("'").strip()
    chemin = os.path.expanduser(chemin)
    # "C:" seul designe le dossier courant du lecteur C, pas sa racine
    if EST_WINDOWS and re.fullmatch(r"[A-Za-z]:", chemin):
        chemin += "\\"
    return Path(os.path.abspath(chemin))


def cle_chemin(chemin) -> str:
    """Forme canonique d'un chemin pour les comparaisons (casse ignoree sous Windows)."""
    return os.path.normcase(os.path.realpath(str(chemin)))


def est_dans(chemin, dossier) -> bool:
    """True si chemin est egal a dossier ou se trouve a l'interieur."""
    c, d = cle_chemin(chemin), cle_chemin(dossier)
    return c == d or c.startswith(d.rstrip(os.sep) + os.sep)


def attributs_windows(chemin) -> int:
    """Retourne les attributs Windows d'un chemin (0 hors Windows ou en cas d'erreur)."""
    if not EST_WINDOWS:
        return 0
    try:
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(chemin))
        return 0 if attrs == -1 else attrs
    except Exception:
        return 0


ATTR_CACHE         = 0x2
ATTR_SYSTEME       = 0x4
ATTR_POINT_ANALYSE = 0x400   # lien symbolique ou jonction NTFS


def est_cache_ou_systeme(chemin) -> bool:
    """True si l'element est cache (nom en .xxx ou attribut Windows) ou systeme."""
    if os.path.basename(str(chemin).rstrip("\\/")).startswith("."):
        return True
    return bool(attributs_windows(chemin) & (ATTR_CACHE | ATTR_SYSTEME))


def est_lien(chemin) -> bool:
    """True pour un lien symbolique ou une jonction NTFS (jamais suivis)."""
    try:
        if os.path.islink(chemin):
            return True
        est_jonction = getattr(os.path, "isjunction", None)
        if est_jonction and est_jonction(chemin):
            return True
    except OSError:
        return True
    return bool(attributs_windows(chemin) & ATTR_POINT_ANALYSE)


def racines_protegees(dossier_destination: str | None, dossier_travail: Path) -> set:
    """
    Construit l'ensemble des dossiers jamais parcourus, en chemin canonique :
    dossiers systeme de l'OS, dossier de destination et dossier de travail
    de ClariFile.
    """
    racines = set()
    if EST_WINDOWS:
        for var in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)",
                    "ProgramW6432", "ProgramData", "APPDATA", "LOCALAPPDATA"):
            valeur = os.environ.get(var)
            if valeur:
                racines.add(cle_chemin(valeur))
    else:
        racines |= {cle_chemin(p) for p in RACINES_SYSTEME_UNIX}
        if sys.platform == "darwin":
            racines |= {cle_chemin(p) for p in ("/System", "/Library",
                                                "/Applications", "/private")}
            racines.add(cle_chemin(Path.home() / "Library"))
    if dossier_destination:
        racines.add(cle_chemin(dossier_destination))
    racines.add(cle_chemin(dossier_travail))
    return racines


def raison_protection_dossier(dossier: str, contexte: dict,
                              noms_fichiers=None, noms_dossiers=None) -> str | None:
    """
    Retourne la raison pour laquelle un dossier ne doit pas etre parcouru,
    ou None s'il peut l'etre. Si les listes de contenu ne sont pas fournies,
    le dossier est lu (resultat mis en cache dans le contexte).
    """
    cache = contexte.setdefault("cache", {})
    cle = cle_chemin(dossier)
    if cle in cache:
        return cache[cle]

    raison = None
    nom = os.path.basename(dossier.rstrip("\\/")).lower()

    if cle in contexte["racines"]:
        raison = "dossier systeme ou reserve a ClariFile"
    elif nom in DOSSIERS_INTERDITS:
        raison = "dossier systeme"
    elif nom and est_cache_ou_systeme(dossier):
        raison = "dossier cache ou systeme (configurations)"
    else:
        for exclu in contexte["exclusions"]:
            if os.sep in exclu or "/" in exclu:
                if est_dans(dossier, exclu):
                    raison = "exclusion personnalisee"
                    break
            elif nom == exclu.lower():
                raison = "exclusion personnalisee"
                break

    # Une racine de disque (C:\, /) ou le dossier personnel n'est jamais une
    # application ni un projet : seul le marqueur y est recherche.
    chemin = Path(dossier)
    detection_contenu = (chemin.parent != chemin
                         and cle != cle_chemin(Path.home()))

    if raison is None:
        if noms_fichiers is None or noms_dossiers is None:
            noms_fichiers, noms_dossiers = [], []
            try:
                with os.scandir(dossier) as it:
                    for entree in it:
                        (noms_dossiers if entree.is_dir(follow_symlinks=False)
                         else noms_fichiers).append(entree.name)
            except OSError:
                pass
        contenu = {n.lower() for n in noms_fichiers} | {n.lower() for n in noms_dossiers}
        suffixes = {os.path.splitext(n)[1] for n in contenu}
        if NOM_MARQUEUR_IGNORE in contenu:
            raison = f"marqueur {NOM_MARQUEUR_IGNORE}"
        elif not detection_contenu:
            pass
        elif (suffixes & EXTENSIONS_BIBLIOTHEQUE
              or any(re.search(r"\.so(\.\d+)+$", n) for n in contenu)):
            raison = "dossier d'application (bibliotheques detectees)"
        elif suffixes & EXTENSIONS_MANIFESTE:
            raison = "dossier d'application (manifeste detecte)"
        elif contenu & MARQUEURS_PROJET or suffixes & EXTENSIONS_PROJET:
            raison = "projet de code"

    cache[cle] = raison
    return raison


def raison_protection_chemin(chemin: Path, contexte: dict) -> str | None:
    """Verifie un fichier et chacun de ses dossiers parents (mode Propositions)."""
    for parent in reversed(chemin.parents):
        raison = raison_protection_dossier(str(parent), contexte)
        if raison:
            return raison
    return None


def extension_interdite(chemin: Path) -> bool:
    return chemin.suffix.lower() in EXTENSIONS_INTERDITES


def nettoyer_nom(texte, defaut: str = "Inconnu") -> str:
    """
    Transforme un texte venant d'une metadonnee en nom de dossier sur.
    Bloque la traversee de chemin (.. ou separateurs), les caracteres
    interdits et les noms reserves de Windows.
    """
    if not texte:
        return defaut
    texte = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(texte))
    texte = texte.strip().strip(".").strip()[:100].strip()
    if not texte:
        return defaut
    if texte.split(".")[0].lower() in NOMS_RESERVES_WINDOWS:
        texte = "_" + texte
    return texte


def dossier_travail() -> Path:
    """Dossier des fichiers internes de ClariFile, selon le systeme."""
    if EST_WINDOWS:
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        dossier = Path(base) / "ClariFile"
    elif sys.platform == "darwin":
        dossier = Path.home() / "Library" / "Application Support" / "ClariFile"
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        dossier = Path(base) / "clarifile"
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def demander_oui(question: str) -> bool:
    """Pose une question fermee. Accepte oui / o (insensible a la casse)."""
    return input(f"  {question} (oui/non) : ").strip().lower() in ("oui", "o")


def tronquer(texte: str, max_len: int = 60) -> str:
    """Tronque un texte long avec '...' au centre."""
    if len(texte) <= max_len:
        return texte
    moitie = (max_len - 3) // 2
    return texte[:moitie] + "..." + texte[-(max_len - moitie - 3):]


def taille_lisible(octets: int) -> str:
    """Convertit une taille en octets en chaine lisible."""
    for unite in ("o", "Ko", "Mo", "Go", "To"):
        if abs(octets) < 1024.0:
            return f"{octets:.1f} {unite}"
        octets /= 1024.0
    return f"{octets:.1f} Po"


TAILLE_BLOC = 1024 * 1024


def empreinte_fichier(chemin: Path, limite: int | None = None) -> str:
    """
    Empreinte BLAKE2b d'un fichier (resistante aux collisions, rapide).
    limite : nombre d'octets lus depuis le debut (None = fichier entier).
    Retourne une chaine vide en cas d'erreur de lecture.
    """
    h = hashlib.blake2b(digest_size=32)
    reste = limite
    try:
        with open(chemin, "rb") as f:
            while reste is None or reste > 0:
                taille = TAILLE_BLOC if reste is None else min(TAILLE_BLOC, reste)
                bloc = f.read(taille)
                if not bloc:
                    break
                h.update(bloc)
                if reste is not None:
                    reste -= len(bloc)
        return h.hexdigest()
    except Exception:
        return ""


def destination_sans_ecrasement(dest: Path) -> Path:
    """Retourne un chemin destination sans ecraser un fichier existant."""
    if not dest.exists():
        return dest
    base = dest.stem
    suffixe = dest.suffix
    dossier = dest.parent
    compteur = 2
    while True:
        nouveau = dossier / f"{base}_{compteur}{suffixe}"
        if not nouveau.exists():
            return nouveau
        compteur += 1


# ─────────────────────────────────────────────────────────────────────────────
# BARRE DE PROGRESSION
# ─────────────────────────────────────────────────────────────────────────────

class BarreProgression:
    """Affiche et met a jour une barre de progression ASCII sur une seule ligne."""

    def __init__(self, total: int, label: str = "Traitement", largeur: int = 20):
        self.total   = max(total, 1)
        self.label   = label
        self.largeur = largeur
        self.actuel  = 0
        self._derniere_maj = -1

    def maj(self, actuel: int, fichier_en_cours: str = ""):
        """Met a jour la barre. Affiche toutes les 50 operations ou au changement."""
        self.actuel = actuel
        # Mise a jour toutes les 50 fichiers, ou au debut/fin
        if actuel != self.total and actuel != 0 and (actuel - self._derniere_maj) < 50:
            return
        self._derniere_maj = actuel
        self._dessiner(fichier_en_cours)

    def _dessiner(self, fichier_en_cours: str = ""):
        pct = self.actuel / self.total
        rempli = int(self.largeur * pct)
        barre = "=" * rempli
        if rempli < self.largeur:
            barre += ">"
            barre += " " * (self.largeur - rempli - 1)
        else:
            barre = "=" * self.largeur
        ligne = f"  {self.label:<12} : [{barre}] {int(pct*100):3d}% - {self.actuel}/{self.total}"
        if fichier_en_cours:
            ligne += "  " + tronquer(fichier_en_cours, 50)
        # Effacer le reste de la ligne precedente avec des espaces, puis retour chariot
        print(f"\r{ligne:<110}", end="", flush=True)

    def terminer(self):
        self._dessiner()
        print()  # Saut de ligne final


# ─────────────────────────────────────────────────────────────────────────────
# HISTORIQUE PROTEGE PAR MOT DE PASSE
# Le mot de passe est un verrou de consultation dans le menu : l'historique
# reste un fichier texte lisible par quiconque a acces au dossier de travail.
# ─────────────────────────────────────────────────────────────────────────────

ITERATIONS_PBKDF2 = 200_000


def hash_mdp(mdp: str, sel: bytes | None = None) -> str:
    """Hache un mot de passe avec PBKDF2-SHA256 sale. Format : pbkdf2$iter$sel$hash."""
    sel = sel or os.urandom(16)
    cle = hashlib.pbkdf2_hmac("sha256", mdp.encode("utf-8"), sel, ITERATIONS_PBKDF2)
    return f"pbkdf2${ITERATIONS_PBKDF2}${sel.hex()}${cle.hex()}"


def mdp_correct(mdp: str, stocke: str) -> bool:
    """Compare en temps constant. Accepte aussi l'ancien format SHA-256 non sale."""
    try:
        if stocke.startswith("pbkdf2$"):
            _, iterations, sel_hex, attendu = stocke.split("$")
            calcule = hashlib.pbkdf2_hmac("sha256", mdp.encode("utf-8"),
                                          bytes.fromhex(sel_hex), int(iterations)).hex()
        else:
            calcule, attendu = hashlib.sha256(mdp.encode("utf-8")).hexdigest(), stocke
        return hmac.compare_digest(calcule, attendu)
    except Exception:
        return False


def creer_historique(chemin_log: Path, chemin_cle: Path):
    """Premier lancement : demande un mot de passe et cree les fichiers historique."""
    print("")
    print("  Premier lancement : creation de l'historique des sessions.")
    print("  Definir un mot de passe pour en proteger la consultation")
    print("  (laisser vide pour ne pas proteger). La saisie reste invisible.")
    mdp = getpass.getpass("  Mot de passe : ")
    if mdp and getpass.getpass("  Confirmation : ") != mdp:
        print("  Les deux saisies different. Historique non protege.")
        mdp = ""
    chemin_cle.write_text(hash_mdp(mdp) if mdp else "NOPASSWORD", encoding="utf-8")
    chemin_log.write_text(
        f"=== ClariFile - Historique des sessions ===\n"
        f"Cree le {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n",
        encoding="utf-8"
    )
    print("  Historique protege par mot de passe." if mdp else "  Historique non protege.")


def verifier_mot_de_passe(chemin_cle: Path) -> str | None:
    """Demande le mot de passe et le verifie. Retourne le mot de passe si correct."""
    cle_stockee = chemin_cle.read_text(encoding="utf-8").strip()
    if cle_stockee == "NOPASSWORD":
        return ""
    print("")
    mdp = getpass.getpass("  Mot de passe de l'historique : ")
    if mdp_correct(mdp, cle_stockee):
        return mdp
    print("  Mot de passe incorrect.")
    return None


def ecrire_historique(chemin_log: Path, chemin_cle: Path, entree: str):
    """Ajoute une entree a l'historique."""
    try:
        if not chemin_cle.exists():
            return
        horodatage = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ligne = f"[{horodatage}] {entree}\n"
        with open(chemin_log, "a", encoding="utf-8") as f:
            f.write(ligne)
    except Exception:
        pass


def afficher_historique(chemin_log: Path, chemin_cle: Path):
    """Affiche le contenu de l'historique apres verification du mot de passe."""
    if not chemin_log.exists():
        print("  Aucun historique disponible.")
        return
    if not chemin_cle.exists():
        print("  Cle de l'historique absente : consultation impossible.")
        return
    mdp = verifier_mot_de_passe(chemin_cle)
    if mdp is None:
        if demander_oui("Historique inaccessible. Le reinitialiser (son contenu sera efface) ?"):
            chemin_log.unlink(missing_ok=True)
            chemin_cle.unlink(missing_ok=True)
            print("  Historique reinitialise.")
        return
    try:
        contenu = chemin_log.read_text(encoding="utf-8")
        print("")
        print(contenu)
    except Exception as e:
        print(f"  Erreur lecture historique : {e}")


# ─────────────────────────────────────────────────────────────────────────────
# EXCLUSIONS PERSONNALISEES
# Une ligne contenant un separateur (/ ou \) est un chemin : le dossier et
# tout son contenu sont exclus. Sinon c'est un nom de dossier, exclu partout
# ou il apparait (comparaison insensible a la casse).
# ─────────────────────────────────────────────────────────────────────────────

def charger_exclusions(chemin_exclusions: Path) -> set:
    """Charge les exclusions personnalisees depuis le fichier de sauvegarde."""
    exclusions = set()
    if chemin_exclusions.exists():
        try:
            for ligne in chemin_exclusions.read_text(encoding="utf-8").splitlines():
                ligne = ligne.strip()
                if ligne and not ligne.startswith("#"):
                    exclusions.add(ligne)
        except Exception:
            pass
    return exclusions


def sauvegarder_exclusions(chemin_exclusions: Path, exclusions: set):
    try:
        lignes = [
            "# ClariFile - Dossiers exclus",
            "# Un chemin complet par ligne, ou un simple nom de dossier.",
        ]
        lignes += sorted(exclusions)
        chemin_exclusions.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    except Exception as e:
        print(f"  Attention : impossible de sauvegarder les exclusions : {e}")


def demander_exclusions(chemin_exclusions: Path) -> set:
    """En mode avance, propose d'ajouter des exclusions."""
    exclusions = charger_exclusions(chemin_exclusions)
    if exclusions:
        print(f"  {len(exclusions)} exclusion(s) deja enregistree(s) dans {chemin_exclusions}")
    if not demander_oui("Exclure des dossiers supplementaires ?"):
        return exclusions
    print("  Saisir un chemin complet ou un nom de dossier par ligne (ligne vide pour terminer).")
    while True:
        saisie = input("  Dossier a exclure : ").strip().strip('"').strip("'")
        if not saisie:
            break
        if os.sep in saisie or "/" in saisie or saisie.startswith("~"):
            saisie = str(normaliser_chemin(saisie))
        exclusions.add(saisie)
        print(f"  Ajoute : {saisie}")
    sauvegarder_exclusions(chemin_exclusions, exclusions)
    return exclusions


# ─────────────────────────────────────────────────────────────────────────────
# DETECTION DES ORPHELINS
# Un orphelin est un fichier signale dans un rapport pour verification
# manuelle. Seuls les fichiers vides sont bloques ; un nom etrange est
# seulement signale, le fichier est range normalement.
# ─────────────────────────────────────────────────────────────────────────────

# Noms faits uniquement d'une date et d'une heure (appareils photo, telephones)
PATTERN_DATE = re.compile(r"^\D{0,6}\d{6,8}[_\-\s]?\d{0,6}\D{0,6}$")


def est_orphelin(chemin: Path, taille: int) -> tuple:
    """
    Retourne (raison, bloquant). raison vaut None si le fichier est normal.
    bloquant = True : le fichier n'est pas deplace.
    """
    if taille == 0:
        return "fichier vide (0 octet)", True
    nom_sans_ext = chemin.stem
    if PATTERN_DATE.match(nom_sans_ext):
        return None, False
    if PATTERN_ALEATOIRE.match(nom_sans_ext):
        return f"nom potentiellement aleatoire ({nom_sans_ext!r})", False
    lettres = re.sub(r"[^a-zA-Z]", "", nom_sans_ext)
    if len(lettres) < 3:
        return f"nom peu significatif ({nom_sans_ext!r})", False
    return None, False


def ecrire_rapport_orphelins(chemin_rapport: Path, orphelins: list):
    """Ecrit le rapport des fichiers orphelins dans un fichier texte."""
    try:
        lignes = [
            "=== ClariFile - Rapport des fichiers orphelins ===",
            f"Genere le {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Total : {len(orphelins)} fichier(s)",
            "",
        ]
        for chemin, raison, taille in orphelins:
            lignes.append(f"  Chemin : {chemin}")
            if taille is not None:
                lignes.append(f"  Taille : {taille_lisible(taille)}")
            lignes.append(f"  Raison : {raison}")
            lignes.append("")
        chemin_rapport.write_text("\n".join(lignes), encoding="utf-8")
        print(f"  Rapport orphelins : {chemin_rapport}")
    except Exception as e:
        print(f"  Erreur ecriture rapport orphelins : {e}")


# ─────────────────────────────────────────────────────────────────────────────
# DETECTION DES DOUBLONS
# Trois filtres successifs, du moins couteux au plus couteux :
#   1. taille identique (aucune lecture disque),
#   2. empreinte des 64 premiers Ko,
#   3. empreinte du fichier entier.
# La grande majorite des fichiers est ecartee des l'etape 1.
# ─────────────────────────────────────────────────────────────────────────────

TAILLE_EMPREINTE_PARTIELLE = 64 * 1024


def detecter_doublons(fichiers: list) -> dict:
    """
    fichiers : liste de tuples (Path, taille_en_octets).
    Retourne {empreinte: [chemins]} pour chaque groupe d'au moins 2 copies.
    """
    def regrouper(groupes, fonction_cle):
        resultat = {}
        for groupe in groupes:
            if len(groupe) < 2:
                continue
            for chemin in groupe:
                cle = fonction_cle(chemin)
                if cle:
                    resultat.setdefault(cle, []).append(chemin)
        return resultat

    par_taille = {}
    for chemin, taille in fichiers:
        if taille > 0:
            par_taille.setdefault(taille, []).append(chemin)

    par_debut = regrouper(
        par_taille.values(),
        lambda c: empreinte_fichier(c, TAILLE_EMPREINTE_PARTIELLE),
    )
    complets = regrouper(par_debut.values(), empreinte_fichier)
    return {h: v for h, v in complets.items() if len(v) > 1}


def afficher_avertissement_doublons(nb_doublons: int):
    """Affiche le message de signalement des doublons."""
    if nb_doublons == 0:
        return
    print("")
    print(f"  {nb_doublons} fichier(s) en double detecte(s) : ils ne seront pas deplaces.")
    print("  Il est conseille de les traiter avec un outil de deduplication")
    print("  avant d'organiser, afin de choisir la copie a conserver.")
    print("")


# ─────────────────────────────────────────────────────────────────────────────
# LECTURE DES METADONNEES
# ─────────────────────────────────────────────────────────────────────────────

def lire_date_exif(chemin: Path) -> datetime | None:
    """Retourne la date de prise de vue EXIF d'une image, ou None."""
    if not PILLOW_OK:
        return None
    try:
        with Image.open(chemin) as img:
            lecteur_exif = getattr(img, "_getexif", None)
            exif_data = lecteur_exif() if lecteur_exif else None
        if not exif_data:
            return None
        exif = {TAGS.get(k, k): v for k, v in exif_data.items()}
        for champ in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
            if champ in exif:
                try:
                    date = datetime.strptime(str(exif[champ]).strip(), "%Y:%m:%d %H:%M:%S")
                    if 1900 < date.year <= datetime.now().year + 1:
                        return date
                except Exception:
                    pass
    except Exception:
        pass
    return None


def lire_tags_audio(chemin: Path) -> dict:
    """
    Lit les tags audio (artiste, album).
    Retourne dict avec cles 'artiste', 'album'.
    """
    if not MUTAGEN_OK:
        return {"artiste": None, "album": None}
    artiste = None
    album = None
    try:
        ext = chemin.suffix.lower()
        if ext == ".mp3":
            tags = EasyID3(chemin)
            artiste = tags.get("artist", [None])[0]
            album   = tags.get("album",  [None])[0]
        elif ext == ".flac":
            tags = FLAC(chemin)
            artiste = tags.get("artist", [None])[0]
            album   = tags.get("album",  [None])[0]
        elif ext in (".m4a", ".mp4", ".aac"):
            tags = MP4(chemin)
            artiste = tags.get("\xa9ART", [None])[0]
            album   = tags.get("\xa9alb", [None])[0]
        elif ext == ".ogg":
            tags = OggVorbis(chemin)
            artiste = tags.get("artist", [None])[0]
            album   = tags.get("album",  [None])[0]
        else:
            audio = mutagen.File(chemin)
            if audio:
                artiste = str(audio.get("artist", [None])[0]) if audio.get("artist") else None
                album   = str(audio.get("album",  [None])[0]) if audio.get("album")  else None
    except Exception:
        pass
    # Les tags viennent du fichier lui-meme : ils sont nettoyes avant de
    # servir de nom de dossier (traversee de chemin, caracteres interdits)
    return {
        "artiste": nettoyer_nom(artiste, defaut="") or None,
        "album":   nettoyer_nom(album,   defaut="") or None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# LOGIQUE DE DESTINATION
# ─────────────────────────────────────────────────────────────────────────────

def categorie_fichier(chemin: Path) -> str | None:
    """
    Retourne la categorie d'un fichier selon son extension.
    Retourne None si l'extension n'est dans aucune categorie connue.
    """
    nom = chemin.name.lower()
    # Archives doubles
    for ext_double in (".tar.gz", ".tar.bz2"):
        if nom.endswith(ext_double):
            return "archives"
    suffixe = chemin.suffix.lower()
    for cat, exts in CATEGORIES.items():
        if suffixe in exts:
            return cat
    return None


def date_depuis_timestamp(mtime: float) -> datetime:
    """Convertit une date de modification en datetime, sans jamais echouer."""
    try:
        return datetime.fromtimestamp(mtime)
    except (OverflowError, OSError, ValueError):
        return datetime.now()


def calculer_destination(chemin: Path, cat: str, dossier_base: str,
                         mtime: float) -> tuple:
    """
    Calcule le chemin de destination et la raison du classement.
    Retourne (chemin_destination_str, raison_str).
    mtime : date de modification deja lue lors du parcours.
    """
    base = Path(dossier_base)
    nom  = chemin.name
    modif = date_depuis_timestamp(mtime)

    if cat in ("images", "videos"):
        dossier_cat = "Photos" if cat == "images" else "Videos"
        date_exif = lire_date_exif(chemin) if cat == "images" else None
        if date_exif:
            d = date_exif
            raison = f"Date de prise de vue {d.strftime('%Y-%m-%d')} (EXIF)"
        else:
            d = modif
            raison = f"Date de modification {d.strftime('%Y-%m-%d')}"
        sous = base / dossier_cat / str(d.year) / MOIS_FR[d.month]
        return str(sous / nom), raison

    elif cat == "documents_pdf":
        sous = base / "Documents" / "PDF" / str(modif.year)
        return str(sous / nom), f"Document PDF, annee de modification {modif.year}"

    elif cat == "documents_word":
        sous = base / "Documents" / "Texte" / str(modif.year)
        return str(sous / nom), f"Document texte, annee de modification {modif.year}"

    elif cat == "tableurs":
        sous = base / "Documents" / "Tableurs" / str(modif.year)
        return str(sous / nom), f"Tableur, annee de modification {modif.year}"

    elif cat == "presentations":
        sous = base / "Documents" / "Presentations" / str(modif.year)
        return str(sous / nom), f"Presentation, annee de modification {modif.year}"

    elif cat == "audio":
        tags = lire_tags_audio(chemin)
        artiste = tags["artiste"] or "Inconnu"
        album   = tags["album"]   or "Inconnu"
        sous    = base / "Musique" / artiste / album
        if tags["artiste"]:
            raison = f"Tags audio : artiste={artiste}, album={album}"
        else:
            raison = "Pas de tags audio, classe dans Musique/Inconnu/Inconnu"
        return str(sous / nom), raison

    elif cat == "archives":
        sous = base / "Archives" / str(modif.year)
        return str(sous / nom), f"Archive, annee de modification {modif.year}"

    elif cat == "code":
        # Les projets complets sont proteges en amont : seuls les fichiers
        # de code isoles arrivent ici. Ils sont ranges par langage.
        suffixe = chemin.suffix.lower()
        langage = LANGAGE_CODE.get(suffixe, nettoyer_nom(suffixe.lstrip(".").capitalize()))
        sous = base / "Code" / langage
        return str(sous / nom), f"Fichier de code {langage} isole"

    raise ValueError(f"categorie inconnue : {cat}")


# ─────────────────────────────────────────────────────────────────────────────
# ANALYSE D'UN LECTEUR
# ─────────────────────────────────────────────────────────────────────────────

def creer_contexte(dossier_destination: str, exclusions: set) -> dict:
    """Regroupe ce dont les verifications de securite ont besoin."""
    return {
        "racines":     racines_protegees(dossier_destination, dossier_travail()),
        "exclusions":  set(exclusions),
        "destination": str(normaliser_chemin(dossier_destination)),
        "script":      cle_chemin(Path(__file__).resolve()),
        "cache":       {},
    }


def analyser_lecteur(
    lecteur: str,
    categories_actives: set,
    contexte: dict,
    verbose: bool = True
) -> dict:
    """
    Parcourt un dossier et ses sous-dossiers, sans jamais entrer dans les
    dossiers proteges, et construit le plan de rangement.
    Retourne un dict avec :
      - 'plan'              : liste de (chemin_src, chemin_dest, raison)
      - 'ignores'           : liste de (chemin, raison)
      - 'orphelins'         : liste de (chemin, raison, taille)
      - 'tous_fichiers'     : liste de (chemin, taille) pour les doublons
      - 'dossiers_proteges' : liste de (dossier, raison)
      - 'nb_analyses'       : nombre de fichiers examines
    """
    resultat = {"plan": [], "ignores": [], "orphelins": [], "tous_fichiers": [],
                "dossiers_proteges": [], "nb_analyses": 0}
    plan, ignores, orphelins = resultat["plan"], resultat["ignores"], resultat["orphelins"]
    tous, proteges = resultat["tous_fichiers"], resultat["dossiers_proteges"]
    destination = contexte["destination"]

    racine = normaliser_chemin(lecteur)
    if not racine.is_dir():
        print(f"  [!] Dossier introuvable : {racine}")
        return resultat

    # Les dossiers parents comptent aussi : C:\Program Files\X\data ou
    # /usr/share/y restent proteges meme donnes directement comme point de depart
    for parent in reversed(racine.parents):
        raison = raison_protection_dossier(str(parent), contexte)
        if raison:
            print(f"  [!] {racine} se trouve dans {parent} ({raison}) : rien n'y sera touche.")
            resultat["dossiers_proteges"].append((parent, raison))
            return resultat

    # Etape 1 : parcours avec elagage des dossiers proteges
    print(f"\n  Parcours de {racine} ...")
    candidats = []
    for dossier, sous_dossiers, fichiers in os.walk(racine, topdown=True,
                                                     followlinks=False,
                                                     onerror=lambda e: None):
        raison = raison_protection_dossier(dossier, contexte, fichiers, sous_dossiers)
        if raison:
            proteges.append((Path(dossier), raison))
            sous_dossiers[:] = []
            continue
        # Les liens et jonctions ne sont jamais suivis (boucles, sortie du perimetre)
        sous_dossiers[:] = sorted(d for d in sous_dossiers
                                  if not est_lien(os.path.join(dossier, d)))
        candidats.extend(Path(dossier) / nom for nom in sorted(fichiers))

    if proteges and cle_chemin(proteges[0][0]) == cle_chemin(racine):
        print(f"  [!] {racine} est protege ({proteges[0][1]}) : rien n'y sera touche.")
        return resultat
    if proteges and verbose:
        print(f"  {len(proteges)} dossier(s) protege(s) non parcouru(s).")

    # Etape 2 : examen de chaque fichier, des tests gratuits aux plus couteux
    resultat["nb_analyses"] = len(candidats)
    barre = BarreProgression(len(candidats), label="Analyse", largeur=20)

    for i, chemin in enumerate(candidats):
        barre.maj(i + 1, str(chemin))

        if chemin.name.startswith(".") or chemin.name.lower().startswith("clarifile_"):
            ignores.append((chemin, "fichier cache ou interne"))
            continue
        if extension_interdite(chemin):
            ignores.append((chemin, f"extension protegee ({chemin.suffix})"))
            continue

        cat = categorie_fichier(chemin)
        if cat is None:
            if chemin.suffix == "":
                orphelins.append((chemin, "sans extension", None))
            ignores.append((chemin, "type de fichier non gere"))
            continue
        if "tout" not in categories_actives and cat not in categories_actives:
            ignores.append((chemin, f"categorie {cat} non selectionnee"))
            continue

        # Un seul appel systeme pour taille, date et nature du fichier
        try:
            st = os.lstat(chemin)
        except OSError:
            ignores.append((chemin, "fichier inaccessible"))
            continue
        if not os.path.isfile(chemin) or os.path.islink(chemin):
            ignores.append((chemin, "lien symbolique ou fichier special"))
            continue
        if attributs_windows(chemin) & (ATTR_CACHE | ATTR_SYSTEME):
            ignores.append((chemin, "fichier cache ou systeme"))
            continue
        if cle_chemin(chemin) == contexte["script"]:
            ignores.append((chemin, "script ClariFile"))
            continue

        raison_orphelin, bloquant = est_orphelin(chemin, st.st_size)
        if raison_orphelin:
            orphelins.append((chemin, raison_orphelin, st.st_size))
            if bloquant:
                ignores.append((chemin, f"orphelin : {raison_orphelin}"))
                continue

        tous.append((chemin, st.st_size))

        try:
            dest, raison = calculer_destination(chemin, cat, destination, st.st_mtime)
        except Exception as e:
            ignores.append((chemin, f"erreur calcul destination : {e}"))
            continue
        # Garde-fou final : aucune destination hors du dossier choisi
        if not est_dans(dest, destination):
            ignores.append((chemin, "destination hors du dossier choisi (refusee)"))
            continue
        plan.append((chemin, Path(dest), raison))

    barre.terminer()
    return resultat


# ─────────────────────────────────────────────────────────────────────────────
# AFFICHAGE DU PLAN
# ─────────────────────────────────────────────────────────────────────────────

def afficher_plan(plan: list, verbose: bool = True):
    """Affiche le tableau Fichier actuel -> Destination proposee."""
    if not plan:
        print("  Aucun fichier a deplacer.")
        return
    print("")
    print(f"  {'FICHIER ACTUEL':<45} {'DESTINATION PROPOSEE':<50}")
    print(f"  {'-'*45} {'-'*50}")
    MAX_AFFICHAGE = 50
    for src, dest, raison in plan[:MAX_AFFICHAGE]:
        src_t  = tronquer(str(src),  45)
        dest_t = tronquer(str(dest), 50)
        print(f"  {src_t:<45} {dest_t:<50}")
        if verbose:
            print(f"    Raison : {raison}")
    if len(plan) > MAX_AFFICHAGE:
        print(f"  ... et {len(plan) - MAX_AFFICHAGE} fichier(s) supplementaires (non affiches).")
    print("")
    print(f"  Total : {len(plan)} fichier(s) a deplacer.")


# ─────────────────────────────────────────────────────────────────────────────
# SIMULATION
# ─────────────────────────────────────────────────────────────────────────────

def simuler(plan: list, doublons: dict, orphelins: list, ignores: list,
            nb_analyses: int) -> dict:
    """
    Affiche ce qui serait fait sans rien modifier.
    Retourne les statistiques de simulation.
    """
    print("")
    print("  === MODE SIMULATION (aucun fichier ne sera deplace) ===")
    print("")

    dossiers_crees = set()
    MAX_AFFICHAGE = 50
    for idx, (src, dest, raison) in enumerate(plan):
        dossiers_crees.add(str(dest.parent))
        if idx < MAX_AFFICHAGE:
            print(f"  DEPLACERAIT : {tronquer(str(src), 55)}")
            print(f"            -> {tronquer(str(dest), 55)}")
            print(f"     Raison  : {raison}")
            print("")
    if len(plan) > MAX_AFFICHAGE:
        print(f"  ... et {len(plan) - MAX_AFFICHAGE} autre(s) deplacement(s) non affiche(s).")
        print("")

    # Doublons
    nb_doublons = sum(len(v) for v in doublons.values())
    if nb_doublons:
        print(f"  DOUBLONS DETECTES : {nb_doublons} fichier(s) en double (non deplaces)")

    # Orphelins
    if orphelins:
        print(f"  ORPHELINS DETECTES : {len(orphelins)} fichier(s) signale(s), voir le rapport")

    stats = {
        "analyses":         nb_analyses,
        "a_deplacer":       len(plan),
        "dossiers_a_creer": len(dossiers_crees),
        "ignores":          len(ignores),
        "doublons":         nb_doublons,
        "orphelins":        len(orphelins),
    }
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# EXECUTION REELLE
# ─────────────────────────────────────────────────────────────────────────────

def executer_plan(plan: list, fichier_log: Path) -> tuple:
    """
    Execute le plan de deplacements.
    Retourne (liste_operations_realisees, nb_dossiers_crees).
    Ecrit dans le journal.
    """
    operations  = []  # liste de (src, dest_finale) pour rollback
    dossiers_crees = set()

    barre = BarreProgression(len(plan), label="Deplacement", largeur=20)

    with open(fichier_log, "a", encoding="utf-8") as log:
        try:
            for i, (src, dest, raison) in enumerate(plan):
                barre.maj(i + 1, str(src))
                horodatage = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                try:
                    # Le fichier a pu changer depuis l'analyse
                    if os.path.islink(src) or not os.path.isfile(src):
                        log.write(f"[{horodatage}] IGNORE (absent ou lien) : {src}\n")
                        continue

                    if not dest.parent.exists():
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dossiers_crees.add(str(dest.parent))

                    dest_finale = destination_sans_ecrasement(dest)
                    shutil.move(str(src), str(dest_finale))
                    log.write(f"[{horodatage}] DEPLACE : {src} -> {dest_finale}\n")
                    operations.append((src, dest_finale))

                except PermissionError:
                    log.write(f"[{horodatage}] IGNORE (permission refusee) : {src}\n")
                except OSError as e:
                    log.write(f"[{horodatage}] IGNORE (erreur systeme : {e}) : {src}\n")
                except Exception as e:
                    log.write(f"[{horodatage}] ERREUR : {src} -> {e}\n")
        except KeyboardInterrupt:
            # La liste des operations deja faites est conservee pour le rollback
            log.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] INTERRUPTION apres "
                      f"{len(operations)} deplacement(s)\n")
            print(f"\n\n  Interruption : {len(operations)} fichier(s) deja deplace(s).")

    barre.terminer()
    return operations, len(dossiers_crees)


def supprimer_dossiers_vides(dossier: Path, racine: str):
    """
    Remonte depuis dossier et supprime chaque sous-dossier vide de racine
    (racine elle-meme est conservee). os.rmdir echoue sur un dossier non
    vide : aucun fichier ne peut etre efface par cette fonction.
    """
    while est_dans(dossier, racine) and cle_chemin(dossier) != cle_chemin(racine):
        try:
            os.rmdir(dossier)
        except OSError:
            return
        dossier = dossier.parent


def rollback(operations: list, fichier_log: Path, racine_destination: str | None = None):
    """
    Annule les deplacements en remettant les fichiers a leur emplacement
    d'origine, puis retire les dossiers devenus vides dans la destination.
    """
    if not operations:
        print("  Aucune operation a annuler.")
        return

    print(f"\n  Annulation de {len(operations)} deplacement(s) ...")
    succes = 0
    echecs = 0
    with open(fichier_log, "a", encoding="utf-8") as log:
        for src_original, dest_finale in reversed(operations):
            horodatage = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                # Ne jamais ecraser un fichier recree entre-temps a l'origine
                if os.path.lexists(src_original):
                    raise FileExistsError("un fichier existe deja a l'emplacement d'origine")
                src_original.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dest_finale), str(src_original))
                log.write(f"[{horodatage}] ROLLBACK : {dest_finale} -> {src_original}\n")
                succes += 1
                if racine_destination:
                    supprimer_dossiers_vides(dest_finale.parent, racine_destination)
            except Exception as e:
                echecs += 1
                log.write(f"[{horodatage}] ROLLBACK ECHEC : {dest_finale} -> {e}\n")

    print(f"  Rollback termine : {succes} reussi(s), {echecs} echec(s).")
    if echecs:
        print(f"  Detail des echecs dans le journal : {fichier_log}")


# ─────────────────────────────────────────────────────────────────────────────
# RAPPORT DE STATISTIQUES
# ─────────────────────────────────────────────────────────────────────────────

def afficher_rapport(stats: dict, fichier_log: Path, simulation: bool = False):
    """Affiche le rapport de statistiques et l'ecrit dans le journal."""
    mode_label = "SIMULATION" if simulation else "EXECUTION"
    lignes = [
        "",
        f"  === Rapport ClariFile - {mode_label} ===",
        f"  Date        : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"  Analyses    : {stats.get('analyses', 0)} fichier(s)",
        f"  Deplaces    : {stats.get('deplaces', stats.get('a_deplacer', 0))} fichier(s)",
        f"  Dossiers    : {stats.get('dossiers_crees', stats.get('dossiers_a_creer', 0))} cree(s)",
        f"  Ignores     : {stats.get('ignores', 0)} fichier(s)",
        f"  Doublons    : {stats.get('doublons', 0)} fichier(s)",
        f"  Orphelins   : {stats.get('orphelins', 0)} fichier(s) signale(s)",
        f"  Proteges    : {stats.get('proteges', 0)} dossier(s) non parcouru(s)",
        "",
    ]
    for ligne in lignes:
        print(ligne)

    try:
        with open(fichier_log, "a", encoding="utf-8") as log:
            for ligne in lignes:
                log.write(ligne.strip() + "\n")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# MODE PROPOSITIONS
# Etape 1 : un fichier texte liste chaque deplacement prevu.
# Etape 2 : apres ajout de OK en fin de ligne DESTINATION PROPOSEE pour les
#           deplacements retenus, un nouveau lancement du mode 3 les execute.
# Le fichier etant modifiable a la main, chaque ligne validee est reverifiee
# avec les memes protections que lors de l'analyse.
# ─────────────────────────────────────────────────────────────────────────────

ENTETE_RACINE = "DOSSIER DE DESTINATION :"
PREFIXE_SRC   = "FICHIER ACTUEL       :"
PREFIXE_DEST  = "DESTINATION PROPOSEE :"
PREFIXE_RAIS  = "RAISON               :"
MOTIF_OK      = re.compile(r"^(.*\S)\s+OK\s*$", re.IGNORECASE)


def ecrire_fichier_propositions(plan: list, chemin_prop: Path, destination: str):
    """Ecrit le fichier de propositions au format texte editable."""
    try:
        lignes = [
            "=== ClariFile - Fichier de propositions ===",
            "Pour valider un deplacement : ajouter un espace puis OK a la fin de",
            "sa ligne DESTINATION PROPOSEE. Le chemin de destination peut etre",
            "modifie, a condition de rester dans le dossier de destination.",
            "Les blocs non valides sont ignores. Ne pas modifier la ligne suivante.",
            f"{ENTETE_RACINE} {destination}",
            f"Genere le {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]
        for src, dest, raison in plan:
            lignes.append(f"{PREFIXE_SRC} {src}")
            lignes.append(f"{PREFIXE_DEST} {dest}")
            lignes.append(f"{PREFIXE_RAIS} {raison}")
            lignes.append("")
        chemin_prop.write_text("\n".join(lignes), encoding="utf-8")
        print(f"\n  Fichier de propositions ecrit : {chemin_prop}")
    except Exception as e:
        print(f"  Erreur ecriture propositions : {e}")


def lire_propositions_validees(chemin_prop: Path) -> tuple:
    """
    Relit le fichier de propositions.
    Retourne (dossier_destination, [(src, dest, raison), ...]) pour les blocs
    dont la ligne DESTINATION PROPOSEE se termine par " OK".
    """
    if not chemin_prop.exists():
        print(f"  Fichier introuvable : {chemin_prop}")
        return None, []

    destination = None
    validees = []
    try:
        contenu = chemin_prop.read_text(encoding="utf-8")
        for ligne in contenu.splitlines():
            if ligne.startswith(ENTETE_RACINE):
                destination = ligne[len(ENTETE_RACINE):].strip()
                break
        for bloc in re.split(r"\n\s*\n", contenu.strip()):
            src = dest = raison = None
            for ligne in bloc.splitlines():
                if ligne.startswith(PREFIXE_SRC):
                    src = ligne[len(PREFIXE_SRC):].strip()
                elif ligne.startswith(PREFIXE_DEST):
                    trouve = MOTIF_OK.match(ligne[len(PREFIXE_DEST):].strip())
                    dest = trouve.group(1).strip() if trouve else None
                elif ligne.startswith(PREFIXE_RAIS):
                    raison = ligne[len(PREFIXE_RAIS):].strip()
            if src and dest:
                validees.append((Path(src), Path(dest), raison or ""))
    except Exception as e:
        print(f"  Erreur lecture propositions : {e}")

    return destination, validees


def verifier_propositions(validees: list, contexte: dict) -> tuple:
    """
    Applique aux propositions validees les memes controles que l'analyse.
    Retourne (plan_sur, refus) ou refus = [(src, raison)].
    """
    plan, refus = [], []
    destination = contexte["destination"]
    for src, dest, raison in validees:
        if not src.is_absolute() or not dest.is_absolute():
            refus.append((src, "chemin relatif refuse"))
        elif os.path.islink(src) or not src.is_file():
            refus.append((src, "fichier source absent ou lien"))
        elif extension_interdite(src) or src.name.startswith("."):
            refus.append((src, "type de fichier protege"))
        elif raison_protection_chemin(src, contexte):
            refus.append((src, raison_protection_chemin(src, contexte)))
        elif not est_dans(dest, destination) or cle_chemin(dest) == cle_chemin(destination):
            refus.append((src, "destination hors du dossier de destination"))
        elif nettoyer_nom(dest.name, defaut="") != dest.name:
            refus.append((src, "nom de destination invalide"))
        else:
            plan.append((src, dest, raison))
    return plan, refus


def mode_propositions(
    chemin_prop: Path,
    chemin_exclusions: Path,
    fichier_log: Path,
    orphelins_path: Path,
    chemin_historique: Path,
    chemin_historique_cle: Path,
):
    """Orchestre le mode Propositions complet."""
    print("\n  --- Mode Propositions ---")

    if chemin_prop.exists():
        print(f"  Un fichier de propositions existe : {chemin_prop}")
        print("    [1] Executer les propositions validees par OK")
        print("    [2] Generer un nouveau fichier (remplace l'actuel)")
        print("    [3] Retour au menu")
        choix = input("  Choix : ").strip()
        if choix == "1":
            executer_propositions(chemin_prop, chemin_exclusions, fichier_log,
                                  chemin_historique, chemin_historique_cle)
            return
        if choix != "2":
            return

    lecteurs            = demander_lecteurs()
    dossier_destination = demander_dossier_destination(lecteurs)
    contexte = creer_contexte(dossier_destination, charger_exclusions(chemin_exclusions))

    plan_total, orphelins_total = [], []
    for lecteur in lecteurs:
        resultat = analyser_lecteur(lecteur, {"tout"}, contexte)
        plan_total      += resultat["plan"]
        orphelins_total += resultat["orphelins"]

    ecrire_fichier_propositions(plan_total, chemin_prop, contexte["destination"])
    if orphelins_total:
        ecrire_rapport_orphelins(orphelins_path, orphelins_total)

    print(f"\n  {len(plan_total)} proposition(s) generee(s). Aucun fichier n'a ete deplace.")
    print("  Etape suivante : ouvrir le fichier, ajouter OK a la fin des lignes")
    print("  DESTINATION PROPOSEE a retenir, enregistrer, puis relancer le mode 3")
    print("  et choisir l'option 1.")


def executer_propositions(
    chemin_prop: Path,
    chemin_exclusions: Path,
    fichier_log: Path,
    chemin_historique: Path,
    chemin_historique_cle: Path,
):
    """Execute les propositions validees apres reverification."""
    destination, validees = lire_propositions_validees(chemin_prop)
    if not destination:
        print("  Ligne 'DOSSIER DE DESTINATION' absente : fichier refuse.")
        return
    if not validees:
        print("  Aucune proposition validee par OK.")
        return

    contexte = creer_contexte(destination, charger_exclusions(chemin_exclusions))
    plan, refus = verifier_propositions(validees, contexte)

    print(f"\n  {len(validees)} proposition(s) validee(s), {len(plan)} acceptee(s), "
          f"{len(refus)} refusee(s).")
    for src, raison in refus[:20]:
        print(f"    REFUSE : {tronquer(str(src), 55)} ({raison})")
    if len(refus) > 20:
        print(f"    ... et {len(refus) - 20} autre(s) refus.")
    if not plan:
        return
    if not demander_oui(f"Deplacer {len(plan)} fichier(s) vers {destination} ?"):
        print("  Execution annulee.")
        return

    operations, nb_dossiers = executer_plan(plan, fichier_log)
    stats = {
        "analyses":       len(validees),
        "deplaces":       len(operations),
        "dossiers_crees": nb_dossiers,
        "ignores":        len(validees) - len(operations),
        "doublons":       0,
        "orphelins":      0,
    }
    afficher_rapport(stats, fichier_log, simulation=False)
    ecrire_historique(chemin_historique, chemin_historique_cle,
                      f"Mode Propositions : {len(operations)} fichier(s) deplace(s)")
    proposer_rollback(operations, fichier_log, chemin_historique, chemin_historique_cle,
                      contexte["destination"])


# ─────────────────────────────────────────────────────────────────────────────
# ORCHESTRATION PRINCIPALE (Simple et Avance)
# ─────────────────────────────────────────────────────────────────────────────

def proposer_rollback(operations: list, fichier_log: Path,
                      chemin_historique: Path, chemin_historique_cle: Path,
                      racine_destination: str):
    """Propose d'annuler les deplacements qui viennent d'etre faits."""
    if not operations:
        print(f"  Aucun fichier deplace. Journal : {fichier_log}")
        return
    print("")
    annuler = input("  Taper 'annuler' pour remettre les fichiers a leur place d'origine,\n"
                    "  ou Entree pour terminer : ").strip().lower()
    if annuler == "annuler":
        rollback(operations, fichier_log, racine_destination)
        ecrire_historique(chemin_historique, chemin_historique_cle,
                          f"Rollback : {len(operations)} deplacement(s) annule(s)")
    else:
        print(f"  Organisation terminee. Journal : {fichier_log}")


def orchestrer(
    lecteurs: list,
    categories_actives: set,
    blacklist_custom: set,
    dossier_destination: str,
    verbose: bool,
    fichier_log: Path,
    orphelins_path: Path,
    chemin_historique: Path,
    chemin_historique_cle: Path,
):
    """
    Orchestre l'analyse, la simulation, la confirmation et l'execution.
    Gere doublons, orphelins, rollback.
    """
    print("\n  Demarrage de l'analyse ...")
    contexte = creer_contexte(dossier_destination, blacklist_custom)
    plan_total      = []
    ignores_total   = []
    orphelins_total = []
    tous_fichiers   = []
    nb_analyses     = 0
    nb_proteges     = 0

    for lecteur in lecteurs:
        resultat = analyser_lecteur(lecteur, categories_actives, contexte, verbose)
        plan_total      += resultat["plan"]
        ignores_total   += resultat["ignores"]
        orphelins_total += resultat["orphelins"]
        tous_fichiers   += resultat["tous_fichiers"]
        nb_analyses     += resultat["nb_analyses"]
        nb_proteges     += len(resultat["dossiers_proteges"])

    if not plan_total:
        print("\n  Aucun fichier a ranger. Rien a faire.")
        return

    # Doublons : toutes les copies d'un meme contenu restent en place,
    # le choix de la copie a garder revenant a un outil de deduplication.
    print("")
    doublons = {}
    if not demander_oui("Ignorer la detection des doublons ?"):
        print("\n  Detection des doublons ...")
        doublons = detecter_doublons(tous_fichiers)
    chemins_doublons = {c for liste in doublons.values() for c in liste}
    plan_sans_doublons = [(s, d, r) for (s, d, r) in plan_total if s not in chemins_doublons]
    nb_doublons = len(chemins_doublons)

    afficher_avertissement_doublons(nb_doublons)

    if orphelins_total:
        ecrire_rapport_orphelins(orphelins_path, orphelins_total)

    afficher_plan(plan_sans_doublons, verbose=verbose)
    if not plan_sans_doublons:
        return

    if demander_oui("Simuler d'abord, sans deplacer aucun fichier ?"):
        stats_sim = simuler(plan_sans_doublons, doublons, orphelins_total,
                            ignores_total, nb_analyses)
        stats_sim["proteges"] = nb_proteges
        afficher_rapport(stats_sim, fichier_log, simulation=True)
        if not demander_oui("Lancer maintenant l'execution reelle ?"):
            print("  Execution annulee.")
            return

    confirmation = input("  Taper 'oui' pour valider et lancer les deplacements : ").strip().lower()
    if confirmation != "oui":
        print("  Execution annulee.")
        return

    print("\n  Execution des deplacements ...")
    operations, nb_dossiers = executer_plan(plan_sans_doublons, fichier_log)

    stats = {
        "analyses":       nb_analyses,
        "deplaces":       len(operations),
        "dossiers_crees": nb_dossiers,
        "ignores":        len(ignores_total),
        "doublons":       nb_doublons,
        "orphelins":      len(orphelins_total),
        "proteges":       nb_proteges,
    }
    afficher_rapport(stats, fichier_log, simulation=False)

    ecrire_historique(
        chemin_historique,
        chemin_historique_cle,
        f"Session terminee : {stats['deplaces']} fichier(s) deplace(s), "
        f"{stats['dossiers_crees']} dossier(s) cree(s)"
    )

    proposer_rollback(operations, fichier_log, chemin_historique, chemin_historique_cle,
                      contexte["destination"])


# ─────────────────────────────────────────────────────────────────────────────
# MENU : DEMANDE DES LECTEURS
# ─────────────────────────────────────────────────────────────────────────────

EXEMPLES_SOURCE = (r"D:\  ou  C:\Users\nom\Downloads" if EST_WINDOWS
                   else "~/Telechargements  ou  /media/nom/DisqueUSB")
DESTINATION_DEFAUT = os.path.join(os.path.expanduser("~"), "ClariFile_Organisation")


def demander_lecteurs() -> list:
    """Demande les dossiers ou lecteurs a analyser. Retourne des chemins absolus."""
    while True:
        print("")
        print("  Dossier(s) ou lecteur(s) a analyser.")
        print(f"  Exemples : {EXEMPLES_SOURCE}")
        print("  Plusieurs chemins : les separer par un point-virgule ( ; )")
        saisie = input("  Chemin(s) : ").strip()
        lecteurs, introuvables = [], []
        for morceau in saisie.split(";"):
            if not morceau.strip():
                continue
            chemin = normaliser_chemin(morceau)
            (lecteurs if chemin.is_dir() else introuvables).append(str(chemin))
        for chemin in introuvables:
            print(f"  [!] Dossier introuvable, ignore : {chemin}")
        if lecteurs:
            return list(dict.fromkeys(lecteurs))
        print("  Aucun dossier valide saisi.")
        if not demander_oui("Recommencer la saisie ?"):
            raise KeyboardInterrupt


def destination_refusee(destination: Path, lecteurs: list) -> str | None:
    """Retourne la raison pour laquelle une destination est dangereuse, ou None."""
    for lecteur in lecteurs:
        if cle_chemin(destination) == cle_chemin(lecteur):
            return "identique a un dossier analyse"
    contexte = {
        "racines": racines_protegees(None, dossier_travail()),
        "exclusions": set(),
        "cache": {},
    }
    for dossier in [destination, *destination.parents]:
        raison = raison_protection_dossier(str(dossier), contexte)
        if raison:
            return f"situee dans un emplacement protege ({raison})"
    return None


def demander_dossier_destination(lecteurs: list) -> str:
    """Demande le dossier de destination et refuse les emplacements dangereux."""
    while True:
        print("")
        print("  Dossier de destination (les sous-dossiers ranges y seront crees).")
        print(f"  Entree pour le dossier par defaut : {DESTINATION_DEFAUT}")
        saisie = input("  Destination : ").strip()
        destination = normaliser_chemin(saisie or DESTINATION_DEFAUT)
        if destination.exists() and not destination.is_dir():
            print("  [!] Ce chemin designe un fichier, pas un dossier.")
            continue
        raison = destination_refusee(destination, lecteurs)
        if raison:
            print(f"  [!] Destination refusee : {raison}.")
            continue
        return str(destination)


# ─────────────────────────────────────────────────────────────────────────────
# MENU : SELECTION DES CATEGORIES (Mode Avance)
# ─────────────────────────────────────────────────────────────────────────────

MENU_CATEGORIES = [
    ("1",  "images",         "Images     : .jpg .jpeg .png .gif .bmp .tiff .webp .heic .raw"),
    ("2",  "videos",         "Videos     : .mp4 .avi .mkv .mov .wmv .flv .mpeg .mpg .m4v"),
    ("3",  "audio",          "Audio      : .mp3 .wav .flac .aac .ogg .m4a .wma"),
    ("4",  "documents_word", "Documents  : .doc .docx .odt .rtf .pdf"),
    ("5",  "tableurs",       "Tableurs   : .xls .xlsx .ods .csv"),
    ("6",  "presentations",  "Presentations : .ppt .pptx .odp"),
    ("7",  "archives",       "Archives   : .zip .tar .gz .rar .7z .tar.gz .tar.bz2"),
    ("8",  "code",           "Code       : .py .js .ts .html .css .php .c .cpp .cs .java .sql .sh"
                             "  (fichiers isoles, hors projets)"),
    ("0",  "tout",           "Tout       : tous les fichiers non proteges"),
]


def demander_categories() -> set:
    """Affiche le menu de categories et retourne l'ensemble des categories choisies."""
    print("")
    print("  Categories de fichiers a traiter (numeros separes par des virgules) :")
    for num, _, label in MENU_CATEGORIES:
        print(f"    [{num}] {label}")
    saisie = input("  Choix : ").strip()
    numeros = [s.strip() for s in saisie.split(",")]
    categories = set()
    for num, cat, _ in MENU_CATEGORIES:
        if num in numeros:
            categories.add(cat)
    # L'option 4 "Documents" couvre Word ET PDF (cf. libelle du menu)
    if "documents_word" in categories:
        categories.add("documents_pdf")
    if not categories:
        print("  Aucune categorie selectionnee. Tout sera traite.")
        categories = {"tout"}
    if "tout" in categories:
        categories = {"tout"}
    return categories


# ─────────────────────────────────────────────────────────────────────────────
# MENU PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def afficher_entete():
    print("")
    print("  ============================================================")
    print("    ClariFile v" + VERSION)
    print("    Organisation automatique de fichiers par type et par date")
    print("  ============================================================")
    print("")


def menu_principal() -> str:
    print("")
    print("  Mode de fonctionnement :")
    print("")
    print("    [1] Mode Simple       - Tous les types de fichiers, reglages par defaut")
    print("    [2] Mode Avance       - Choix des categories et des exclusions")
    print("    [3] Mode Propositions - Fichier de propositions a valider, puis execution")
    print("    [H] Historique        - Consulter l'historique des sessions")
    print("    [Q] Quitter")
    print("")
    choix = input("  Choix : ").strip().upper()
    return choix


# ─────────────────────────────────────────────────────────────────────────────
# MODE SIMPLE
# ─────────────────────────────────────────────────────────────────────────────

def lancer_mode_simple(
    fichier_log: Path,
    orphelins_path: Path,
    chemin_historique: Path,
    chemin_historique_cle: Path,
    chemin_exclusions: Path,
):
    print("\n  --- Mode Simple ---")
    lecteurs = demander_lecteurs()
    dossier_destination = demander_dossier_destination(lecteurs)

    blacklist_custom = charger_exclusions(chemin_exclusions)
    categories_actives = {"tout"}

    orchestrer(
        lecteurs            = lecteurs,
        categories_actives  = categories_actives,
        blacklist_custom    = blacklist_custom,
        dossier_destination = dossier_destination,
        verbose             = False,
        fichier_log         = fichier_log,
        orphelins_path      = orphelins_path,
        chemin_historique   = chemin_historique,
        chemin_historique_cle = chemin_historique_cle,
    )


# ─────────────────────────────────────────────────────────────────────────────
# MODE AVANCE
# ─────────────────────────────────────────────────────────────────────────────

def lancer_mode_avance(
    fichier_log: Path,
    orphelins_path: Path,
    chemin_historique: Path,
    chemin_historique_cle: Path,
    chemin_exclusions: Path,
):
    print("\n  --- Mode Avance ---")
    lecteurs           = demander_lecteurs()
    categories_actives = demander_categories()
    dossier_destination= demander_dossier_destination(lecteurs)
    blacklist_custom   = demander_exclusions(chemin_exclusions)

    orchestrer(
        lecteurs            = lecteurs,
        categories_actives  = categories_actives,
        blacklist_custom    = blacklist_custom,
        dossier_destination = dossier_destination,
        verbose             = True,
        fichier_log         = fichier_log,
        orphelins_path      = orphelins_path,
        chemin_historique   = chemin_historique,
        chemin_historique_cle = chemin_historique_cle,
    )


# ─────────────────────────────────────────────────────────────────────────────
# POINT D'ENTREE
# ─────────────────────────────────────────────────────────────────────────────

def main():
    # Fichiers internes dans le dossier de donnees de l'utilisateur, jamais
    # a cote du script : ils ne finissent pas dans un depot de code publie.
    try:
        dossier = dossier_travail()
    except OSError as e:
        print(f"  Impossible de creer le dossier de travail : {e}")
        sys.exit(1)

    fichier_log           = dossier / NOM_LOG
    orphelins_path        = dossier / NOM_ORPHELINS
    chemin_propositions   = dossier / NOM_PROPOSITIONS
    chemin_historique     = dossier / NOM_HISTORIQUE
    chemin_historique_cle = dossier / NOM_HISTORIQUE_CLE
    chemin_exclusions     = dossier / NOM_EXCLUSIONS

    afficher_entete()
    afficher_etat_dependances()
    print(f"  Dossier de travail : {dossier}")

    # Initialisation historique si premier lancement
    if not chemin_historique_cle.exists():
        creer_historique(chemin_historique, chemin_historique_cle)

    # Boucle menu principale
    while True:
        try:
            choix = menu_principal()

            if choix == "1":
                lancer_mode_simple(
                    fichier_log, orphelins_path,
                    chemin_historique, chemin_historique_cle,
                    chemin_exclusions,
                )

            elif choix == "2":
                lancer_mode_avance(
                    fichier_log, orphelins_path,
                    chemin_historique, chemin_historique_cle,
                    chemin_exclusions,
                )

            elif choix == "3":
                mode_propositions(
                    chemin_prop           = chemin_propositions,
                    chemin_exclusions     = chemin_exclusions,
                    fichier_log           = fichier_log,
                    orphelins_path        = orphelins_path,
                    chemin_historique     = chemin_historique,
                    chemin_historique_cle = chemin_historique_cle,
                )

            elif choix == "H":
                afficher_historique(chemin_historique, chemin_historique_cle)

            elif choix == "Q":
                print("\n  Au revoir.\n")
                sys.exit(0)

            else:
                print("  Choix invalide.")

        except KeyboardInterrupt:
            print("\n\n  Interruption. Arret propre.")
            sys.exit(0)
        except EOFError:
            print("\n\n  Fin du flux d'entree. Arret propre.")
            sys.exit(0)
        except Exception as e:
            print(f"\n  Erreur inattendue : {e}")
            print("  Le script continue.")


if __name__ == "__main__":
    main()
