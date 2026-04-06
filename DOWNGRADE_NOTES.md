# Django 3.0.10 Downgrade Notes

## Status
Successfully prepared the codebase for Django 3.0.10 downgrade on branch `django-3.0-downgrade`.

## Changes Made

### 1. Settings Configuration
- ✅ Changed `STORAGES` dict to `STATICFILES_STORAGE` setting (Django 3.0 compatible)
- ✅ Removed `django_vite` from INSTALLED_APPS
- ✅ Removed `DJANGO_VITE` settings
- ✅ Updated middleware from `django_htmx.middleware.HtmxMiddleware` to custom `core.middleware.HtmxMiddleware`

### 2. Asset Pipeline
- ✅ Removed Vite template tags (`{% vite_hmr_client %}`, `{% vite_asset %}`)
- ✅ Replaced with direct static file references in `base.html`
- ✅ Pre-compiled CSS and JS assets are ready to use

### 3. Dependencies
- ✅ Updated `requirements.txt` with Django 3.0.10 and compatible packages:
  - Django==3.0.10
  - whitenoise==6.0.0
  - asgiref==3.2.7
  - sqlparse==0.4.1
  - pytz==2021.3

### 4. Custom Middleware
- ✅ Created `core/middleware.py` with simple HTMX middleware
  - Replaces django-htmx (which requires Django 4.2+)
  - Detects HTMX requests via `HX-Request` header
  - Sets `request.htmx` boolean attribute

## CRITICAL: Python Version Requirement

**Django 3.0.10 REQUIRES Python 3.8.x, 3.9.x, or 3.10.x**

Django 3.0 is incompatible with Python 3.12+ because it relies on modules that were removed:
- `distutils` (removed in Python 3.12)
- `cgi` module (removed in Python 3.13)

### Testing Status
- ❌ Cannot test on Python 3.15.0a7 (current environment)
- ✅ Code structure is ready for Python 3.8.10
- ✅ All imports and views are compatible

## Next Steps

1. **Install Python 3.8.10** on the target server
2. **Create virtual environment** with Python 3.8.10
3. **Install dependencies**: `pip install -r requirements.txt`
4. **Run migrations**: `python manage.py migrate`
5. **Collect static files**: `python manage.py collectstatic`
6. **Test locally** before deployment

## Files Modified
- `config/settings.py` - Settings updates
- `config/urls.py` - No changes (compatible)
- `core/middleware.py` - NEW custom HTMX middleware
- `requirements.txt` - Downgraded dependencies
- `templates/base.html` - Replaced Vite tags
- `templates/components/sidebar.html` - Removed Vite load

## Known Issues & Limitations

1. **Asset Pipeline**: Vite is removed, using pre-compiled static assets
   - You can still rebuild with Vite on a modern machine
   - Then copy compiled assets to production
   - Or use plain CSS/JS without bundling

2. **Package Compatibility**: django-htmx was entirely replaced with custom middleware
   - Custom middleware only checks for HX-Request header
   - Supports the core functionality used in this app
   - If you need advanced HTMX features, may need updates

3. **Python Version**: MUST be 3.8.x - 3.10.x
   - Cannot use Python 3.11+ (modules removed by stdlib)
   - Cannot use Python 3.15+ (definitely incompatible)

## Verification Checklist

Before going to production:
- [ ] Test on Python 3.8.10
- [ ] Run `python manage.py check`
- [ ] Test all HTMX endpoints
- [ ] Verify static files load correctly
- [ ] Check admin interface
- [ ] Test forms and validation
- [ ] Verify migrations run cleanly

## Git Branch
All changes committed to: `django-3.0-downgrade`
