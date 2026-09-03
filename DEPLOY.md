# Déploiement — TIG sur un VPS via Coolify

## 1. Prérequis
- Coolify installé sur le VPS, avec un projet/application créée depuis ce dépôt Git
  (type de build : **Docker Compose**).
- Un nom de domaine dont le DNS (enregistrement A) pointe vers l'IP du VPS.
- Une clé API Anthropic (console.anthropic.com).

## 2. Configuration dans Coolify
- **Domaine / HTTPS** : renseignez le domaine dans l'onglet "Domains" de la
  ressource. Coolify obtient et renouvelle automatiquement le certificat
  Let's Encrypt via son reverse-proxy intégré (Traefik) — il n'y a **rien à
  configurer côté docker-compose.yml** pour ça, ne rajoutez pas de service
  Caddy/nginx dans le compose : ça entre en conflit avec le proxy de Coolify.
- **Variable d'environnement** : dans l'onglet "Environment Variables" de la
  ressource, ajoutez `ANTHROPIC_API_KEY` avec votre clé. Coolify l'injecte
  automatiquement au conteneur (voir `${ANTHROPIC_API_KEY}` dans
  `docker-compose.yml`).

## 3. Déploiement
Cliquez "Deploy" dans Coolify. Il build l'image, la démarre, et route le
domaine vers le port `3210` exposé par le service `techinox-gestion`.

## 4. Premier démarrage
- Identifiants par défaut : `admin` / `admin` — **changez ce mot de passe
  immédiatement** (Paramètres → Changer mon mot de passe), le site étant
  désormais public.
- Les données (`db.json`, `users.json`, `pdfs/`) vivent dans `./data/` sur le
  VPS (volume monté dans le conteneur), hors de l'image Docker — sauvegardez
  ce dossier régulièrement.

## 5. Mettre à jour le code
Un nouveau push sur `main` (ou "Redeploy" dans Coolify) rebuild l'image.
`./data/` n'est jamais touché par une rebuild — vos articles, factures et
utilisateurs sont conservés.

## 6. Récupérer vos données locales existantes (optionnel)
Si vous avez déjà un catalogue construit en local, copiez le dossier `data/`
vers le VPS avant le premier déploiement (ou après, en redémarrant le
conteneur) :
```bash
scp -r ./data utilisateur@vps:/chemin/vers/l-application/
```

## Déploiement sans Coolify (VPS nu)
Si vous déployez avec un simple `docker compose up -d --build` sans Coolify
en façade, il vous faudra votre propre reverse-proxy HTTPS (Caddy, nginx +
certbot...) devant le port `3210` — non fourni ici puisque Coolify s'en charge.

## Sécurité — ce qui est déjà en place
- La clé API Claude ne vit que dans les variables d'environnement (Coolify ou
  `.env`) côté serveur — jamais transmise au navigateur ni stockée dans `db.json`.
- Mots de passe hashés (PBKDF2, 100k itérations, sel par utilisateur), 8
  caractères minimum.
- Protection anti brute-force sur `/api/login` (5 échecs → verrouillage 15 min).
- HTTPS géré par le reverse-proxy en façade (Coolify/Traefik).

## À faire vous-même
- Si un mot de passe a déjà circulé en clair (email, chat...), changez-le à
  nouveau après le déploiement.
- Sauvegardez `./data/` en dehors du serveur, régulièrement.
