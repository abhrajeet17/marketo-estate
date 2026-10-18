# Deployment Guide

This guide covers multiple deployment options for the Real Estate Plot Marker application.

## 🚀 Quick Deploy Options

### 1. Render (Recommended - Free Tier)

**Pros:** Free tier, automatic HTTPS, easy setup, persistent storage

**Steps:**

1. **Push to GitHub:**
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin <your-github-repo-url>
   git push -u origin main
   ```

2. **Deploy on Render:**
   - Go to [render.com](https://render.com) and sign up
   - Click "New +" → "Web Service"
   - Connect your GitHub repository
   - Configure:
     - **Name:** `real-estate-plot-marker`
     - **Environment:** `Python 3`
     - **Build Command:** `pip install -r requirements.txt`
     - **Start Command:** `gunicorn --pythonpath app-backend -c app-backend/gunicorn.conf.py app:app`
   - Click "Create Web Service"

3. **Environment Variables (Optional):**
   - `FLASK_ENV`: `production`
   - `PORT`: (auto-set by Render)

**Note:** Render provides free persistent disk storage, so your SQLite database and uploads will persist.

---

### 2. Railway (Free Tier)

**Pros:** Free tier, simple deployment, good for small apps

**Steps:**

1. Push your code to GitHub
2. Go to [railway.app](https://railway.app) and sign up
3. Click "New Project" → "Deploy from GitHub repo"
4. Select your repository
5. Railway will auto-detect Python and deploy
6. Add environment variable: `PORT` (auto-set)

**Note:** Railway also provides persistent storage on free tier.

---

### 3. Fly.io (Free Tier)

**Pros:** Global edge deployment, free tier

**Steps:**

1. Install Fly CLI: `curl -L https://fly.io/install.sh | sh`
2. Login: `fly auth login`
3. Initialize: `fly launch`
4. Deploy: `fly deploy`

Create `fly.toml`:
```toml
app = "your-app-name"
primary_region = "iad"

[build]

[env]
  PORT = "8080"

[[services]]
  http_checks = []
  internal_port = 8080
  processes = ["app"]
  protocol = "tcp"
  script_checks = []

  [services.concurrency]
    hard_limit = 25
    soft_limit = 20
    type = "connections"

  [[services.ports]]
    force_https = true
    handlers = ["http"]
    port = 80

  [[services.ports]]
    handlers = ["tls", "http"]
    port = 443

  [[services.tcp_checks]]
    grace_period = "1s"
    interval = "15s"
    restart_limit = 0
    timeout = "2s"
```

---

### 4. PythonAnywhere (Free Tier)

**Pros:** Free tier, Python-focused, simple

**Steps:**

1. Sign up at [pythonanywhere.com](https://www.pythonanywhere.com)
2. Go to "Files" tab and upload your files
3. Go to "Web" tab → "Add a new web app"
4. Choose Flask and Python 3.x
5. Set WSGI file to point to your app
6. Reload web app

**Limitations:** Free tier has limited CPU time and storage.

---

## 💰 Paid Options (More Control)

### 5. DigitalOcean App Platform

**Pros:** Simple, scalable, good pricing

**Steps:**

1. Push to GitHub
2. Go to [DigitalOcean](https://www.digitalocean.com)
3. Create App → Connect GitHub
4. Configure build and run commands
5. Deploy

**Pricing:** Starts at $5/month

---

### 6. Heroku

**Pros:** Well-established, good documentation

**Steps:**

1. Install Heroku CLI
2. Login: `heroku login`
3. Create app: `heroku create your-app-name`
4. Deploy: `git push heroku main`

**Pricing:** No free tier (starts at $5/month)

---

### 7. AWS (Elastic Beanstalk)

**Pros:** Scalable, enterprise-grade

**Steps:**

1. Install EB CLI: `pip install awsebcli`
2. Initialize: `eb init`
3. Create environment: `eb create`
4. Deploy: `eb deploy`

**Pricing:** Pay for EC2 usage (~$10-20/month minimum)

---

## 🔑 Google sign-in (Supabase Auth)

The login page shows **Continue with Google** / **Sign up with Google** automatically once the Google
provider is enabled in Supabase; until then only email sign-in is shown. No app config or redeploy is needed.

1. **Google Cloud Console** → APIs & Services → Credentials → *Create credentials* → *OAuth client ID*
   (configure the OAuth consent screen first if prompted: app name, support email, logo, authorized domain).
   - Application type: **Web application**
   - Authorized JavaScript origins: `http://localhost:5000` and your production URL (e.g. `https://app.example.com`)
   - Authorized redirect URI: `https://<project-ref>.supabase.co/auth/v1/callback`
2. **Supabase Dashboard** → Authentication → Providers → **Google**: enable it and paste the Client ID and Client secret.
3. **Supabase Dashboard** → Authentication → URL Configuration → *Redirect URLs*: add
   `http://localhost:5000/auth/callback` and `https://<your-domain>/auth/callback`.

After Google returns to `/auth/callback`, the app saves the Google name to the profile, accepts any pending
client-team invite, and routes the user: builders to `/projectselection`, client team members to the portal,
and new users without a client group to `/onboarding`.

## 📋 Pre-Deployment Checklist

- [ ] Update `requirements.txt` with all dependencies
- [ ] Create `Procfile` for production server
- [ ] Set `FLASK_ENV=production` in production
- [ ] Ensure `.gitignore` excludes sensitive files
- [ ] Test database migrations (if any)
- [ ] Verify file upload directory permissions
- [ ] Set up environment variables
- [ ] Test locally with `gunicorn --pythonpath app-backend -c app-backend/gunicorn.conf.py app:app`

## 🔧 Production Considerations

### Database
- **SQLite** works for small apps (< 1000 users)
- For larger scale, consider PostgreSQL (Render/Railway offer this)
- Update `get_db()` to use PostgreSQL connection string

### File Storage
- Current setup uses local `uploads/` folder
- For production, consider:
  - **AWS S3** (object storage)
  - **Cloudinary** (image hosting)
  - **Render/Railway persistent disk** (simplest)

### Security
- Set `FLASK_ENV=production` to disable debug mode
- Use environment variables for secrets
- Enable HTTPS (most platforms do this automatically)
- Consider adding authentication if needed

### Performance
- Use `gunicorn` with multiple workers:
  ```bash
  gunicorn --pythonpath app-backend -w 4 -b 0.0.0.0:$PORT app:app
  ```
- Add caching headers for static files
- Consider CDN for static assets

## 🐛 Troubleshooting

### Common Issues:

1. **Port binding error:**
   - Use `0.0.0.0` as host: `app.run(host='0.0.0.0', port=port)`
   - Get port from environment: `os.environ.get('PORT', 5000)`

2. **Database not persisting:**
   - Use persistent disk storage (Render/Railway)
   - Or migrate to PostgreSQL

3. **File uploads not working:**
   - Check directory permissions
   - Ensure `uploads/` directory exists
   - Verify file size limits

4. **Static files not loading:**
   - Check Flask static folder configuration
   - Verify file paths in templates

## 📚 Additional Resources

- [Render Docs](https://render.com/docs)
- [Railway Docs](https://docs.railway.app)
- [Fly.io Docs](https://fly.io/docs)
- [Flask Deployment](https://flask.palletsprojects.com/en/latest/deploying/)

---

**Recommended for beginners:** Render or Railway (both free, easy setup)
**Recommended for production:** DigitalOcean or AWS (more control, better scaling)

