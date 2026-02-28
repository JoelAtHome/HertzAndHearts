# Profile Password & Lockout Recovery

## Overview

Profiles can have optional passwords. If a profile has a password, you must enter it at login to use that profile.

## Lockout Recovery (Testing / Emergency)

If you get locked out during development or testing:

### 1. Environment variable bypass

Set `HNH_SKIP_PASSWORD=1` before starting the app. This skips password verification entirely:

```powershell
$env:HNH_SKIP_PASSWORD="1"; python -m hnh
```

```bash
HNH_SKIP_PASSWORD=1 python -m hnh
```

Once you're in, use **Profile Manager → Set/Reset Password** to clear or change the password.

### 2. Direct SQLite reset

1. Close the app.
2. Open the profiles database (default: `%LOCALAPPDATA%\Hertz-and-Hearts\profiles.db` or `~/.local/share/Hertz-and-Hearts/profiles.db`).
3. Run:

```sql
UPDATE profiles SET password_hash = NULL WHERE name = 'YourProfileName';
```

4. Start the app; the profile will behave as if it has no password.

### 3. Delete and recreate profile

1. Use `HNH_SKIP_PASSWORD=1` to get in.
2. Open Profile Manager, select the locked profile.
3. Archive or delete it (after moving data if needed).
4. Create a new profile with the same settings.

## Creating & Resetting Passwords

### Creating a password (new profile)

1. Click **New Profile...** in the login dialog.
2. Enter a profile name.
3. Enter a password (optional; you can skip).
4. Click **Continue**. The entered password is stored for that profile.

### Creating a password (existing profile without one)

1. Select the profile and enter the desired password in the Password field.
2. Click **Continue**. The new password is stored.

### Resetting a password (when logged in)

1. Open **Profile Manager** (via Settings or the user menu).
2. Select the profile.
3. Click **Set/Reset Password**.
4. Enter the current password (leave blank if none).
5. Enter the new password and confirm.
6. To remove the password, leave both new fields blank.

### Forgot password (lockout)

Use one of the **Lockout Recovery** options above (env var or SQLite) to bypass or clear the password, then set a new one via Profile Manager.
