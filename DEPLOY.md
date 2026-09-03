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
- Les données (`db.json`, `users.json`, `pdfs/`) vivent dans le **volume Docker
  nommé `tig-data`**, monté sur `/app/data` dans le conteneur.

## 5. Persistance des données entre redéploiements
`db.json`, `users.json` et `pdfs/` vivent dans un **volume Docker nommé**
(`tig-data`), pas dans un dossier du dépôt — Docker le gère indépendamment du
répertoire de build que Coolify recrée à chaque déploiement. Un nouveau push
sur `main` (ou "Redeploy" dans Coolify) rebuild l'image applicative **sans
jamais toucher au volume** : vos articles, factures et comptes utilisateurs
sont conservés automatiquement.

⚠️ Le volume n'est perdu que si vous supprimez explicitement la ressource
dans Coolify (ou lancez un `docker compose down -v`) — un simple redeploy ne
le touche jamais.

### Sauvegarder le volume
```bash
# Sur le VPS : archive le contenu du volume dans un fichier .tar.gz local
docker run --rm -v tig-data:/data -v "$(pwd)":/backup alpine \
  tar czf /backup/tig-data-$(date +%Y%m%d).tar.gz -C /data .
```
(le nom réel du volume peut être préfixé par Coolify, ex. `<uuid>_tig-data` —
listez-les avec `docker volume ls | grep tig-data` pour le nom exact)

### Restaurer une sauvegarde
```bash
docker run --rm -v tig-data:/data -v "$(pwd)":/backup alpine \
  sh -c "cd /data && tar xzf /backup/tig-data-20260101.tar.gz"
```

## 6. Récupérer des données locales existantes (optionnel)
Si vous avez un catalogue construit en local (`./data/` sur votre machine),
copiez-le sur le VPS puis chargez-le dans le volume :
```bash
scp -r ./data utilisateur@vps:/tmp/tig-data
ssh utilisateur@vps
docker run --rm -v tig-data:/data -v /tmp/tig-data:/src alpine \
  sh -c "cp -r /src/. /data/"
```

## Déploiement sans Coolify (VPS nu)
Si vous déployez avec un simple `docker compose up -d --build` sans Coolify
en façade, il vous faudra votre propre reverse-proxy HTTPS (Caddy, nginx +
certbot...) devant le port `3210` — non fourni ici puisque Coolify s'en charge.
Le volume nommé `tig-data` fonctionne identiquement (pas besoin de Coolify
pour ça).

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
- Sauvegardez le volume `tig-data` en dehors du serveur, régulièrement (voir
  section 5).
