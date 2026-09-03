# Déploiement — TIG sur un VPS

## 1. Prérequis
- Un VPS avec Docker et Docker Compose installés.
- Un nom de domaine dont le DNS (enregistrement A) pointe vers l'IP du VPS.
- Une clé API Anthropic (console.anthropic.com).

## 2. Configuration
```bash
git clone https://github.com/cmoi1000/TIG---Techinox.git
cd TIG---Techinox
cp .env.example .env        # puis éditez .env et collez votre clé API
```
Éditez `Caddyfile` : remplacez `votre-domaine.fr` par votre vrai domaine.

## 3. Lancement
```bash
docker compose up -d --build
```
Caddy obtient et renouvelle automatiquement le certificat HTTPS (Let's Encrypt) —
assurez-vous que les ports 80 et 443 sont ouverts sur le VPS/pare-feu.

## 4. Premier démarrage
- Identifiants par défaut : `admin` / `admin` — **changez ce mot de passe immédiatement**
  (Paramètres → Changer mon mot de passe), le site étant désormais public.
- Les données (`db.json`, `users.json`, `pdfs/`) vivent dans `./data/` sur le VPS,
  hors de l'image Docker — sauvegardez ce dossier régulièrement.

## 5. Mettre à jour le code
```bash
git pull
docker compose up -d --build
```
`./data/` n'est jamais touché par une rebuild — vos articles, factures et
utilisateurs sont conservés.

## Sécurité — ce qui est déjà en place
- La clé API Claude ne vit que dans `.env` côté serveur — jamais transmise au
  navigateur ni stockée dans `db.json`.
- Mots de passe hashés (PBKDF2, 100k itérations, sel par utilisateur), 8
  caractères minimum.
- Protection anti brute-force sur `/api/login` (5 échecs → verrouillage 15 min).
- HTTPS géré par Caddy devant l'application.

## À faire vous-même
- Si un mot de passe a déjà circulé en clair (email, chat...), changez-le à
  nouveau après le déploiement.
- Sauvegardez `./data/` (via `docker compose exec` ou directement sur le VPS)
  en dehors du serveur, régulièrement.
