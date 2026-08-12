# Security TODO

- [ ] Replace readable passwords in `users.json` with one-way password hashes.
- [ ] Update `list-users.py` so it lists usernames and roles without displaying passwords.
- [ ] Keep `change-password.py` as the recovery method after password hashing is enabled.

Readable credentials are an intentionally accepted temporary risk. The configured shared
root must never include this project directory, `users.json`, or a parent directory that
contains them.
