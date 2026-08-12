# Custom File Server

A small Flask file server with shared storage, role-based access, previews, uploads, and a
purple liquid-glass interface.

## Install and configure

```bash
python -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python setup-server.py
```

Choose a dedicated data directory. The application refuses to use its own project directory
or a parent of the project as shared storage, because that could expose credentials or allow
application code to be overwritten.

## Roles

- `owner`: view, download, upload, create, edit, rename, move, convert, and delete.
- `editor`: everything above except deletion.
- `viewer`: view, search, preview, and download only.

Create an account interactively:

```bash
./.venv/bin/python create-user.py
```

Or specify the role directly:

```bash
./.venv/bin/python create-user.py Lucas --role owner
./.venv/bin/python create-user.py Writer --role editor
./.venv/bin/python create-user.py Guest --role viewer
```

The first account is always made an owner so the server cannot be created without an owner.

List accounts and their current readable UUID passwords:

```bash
./.venv/bin/python list-users.py
```

Rotate a forgotten or exposed password:

```bash
./.venv/bin/python change-password.py Lucas
```

Change an existing account's role:

```bash
./.venv/bin/python change-role.py Guest editor
```

Passwords are temporarily stored in readable form in `users.json`; password hashing remains
documented in `TODO.md`. Keep the project directory and terminal output private.

## Run locally or on the LAN

```bash
./RUN.sh
```

The server listens on the configured port and is reachable through `127.0.0.1` and the
computer's LAN IP. LAN HTTP does not encrypt passwords or files, so use it only on a network
you trust.

## Run with LocalTunnel

```bash
./RUN.sh --tunnel
```

This keeps LAN access and also starts the configured LocalTunnel address. Forwarded proxy
headers are trusted only when the connection to Flask comes from a loopback/local process.

## Upload behavior

All file types are accepted. The default request limit is 20 GiB and can be changed through
`max_upload_bytes` in `config.json`. Existing files are not silently overwritten. Active web
formats such as HTML and SVG are served as plain text for previews, while unknown binaries
download instead of being rendered as web content.
