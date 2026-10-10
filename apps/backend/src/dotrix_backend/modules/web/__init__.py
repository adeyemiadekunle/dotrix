"""The web app's session: httpOnly cookies, refreshing them, and the GitHub sign-in redirects.

The web app is a static single-page app served from the same origin as this API (Vite's dev
proxy locally, a reverse proxy in production), so the API keeps its tokens in cookies the page
can't read. See `router.py` for the routes and `session.py` for the cookies.
"""
