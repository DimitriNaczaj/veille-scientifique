from pathlib import Path

from .atomic import atomic_open
from .mail_diagnostics import (
    MailDiagnosticError,
    _safe_error,
    create_imap_client,
    load_imap_settings,
)
from .models import IMAPSyncReport
from .storage import Store


MAX_SYNC_LIMIT = 10000


def _uidvalidity(client):
    _, values = client.response("UIDVALIDITY")
    if not values or values[0] is None:
        raise RuntimeError("Le serveur IMAP n’a pas fourni UIDVALIDITY.")
    value = values[0]
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="strict")
    return str(value).strip()


def _uids(data):
    if not data or data[0] is None:
        return ()
    return tuple(sorted(int(value) for value in data[0].split()))


def _message_bytes(data):
    for item in data or ():
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    raise RuntimeError("Le serveur IMAP n’a pas renvoyé le message RFC822.")


def _write_message(path, payload):
    with atomic_open(path, "wb") as stream:
        stream.write(payload)


def run_imap_sync(
    config_path,
    inbox,
    database,
    limit=200,
    initial_mode="all",
    client_factory=None,
):
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or limit < 0
        or limit > MAX_SYNC_LIMIT
    ):
        raise ValueError(
            "La limite IMAP doit être comprise entre 0 et {}.".format(MAX_SYNC_LIMIT)
        )
    if initial_mode not in ("all", "latest"):
        raise ValueError("Le mode initial IMAP doit être all ou latest.")
    settings = load_imap_settings(config_path)
    inbox_path = Path(inbox)
    inbox_path.mkdir(parents=True, exist_ok=True)
    client = None
    store = Store(database)
    downloaded = 0
    existing = 0
    skipped_on_initialization = 0
    errors = []
    uidvalidity = ""
    last_uid = 0
    available = 0
    try:
        client = create_imap_client(settings, client_factory)
        client.login(settings.username, settings.password)
        status, _ = client.select(settings.folder, readonly=True)
        if status != "OK":
            raise RuntimeError("Le dossier IMAP n’a pas pu être ouvert en lecture seule.")
        uidvalidity = _uidvalidity(client)
        stored_uid = store.imap_last_uid(
            settings.username, settings.folder, uidvalidity
        )
        previous_uidvalidities = store.imap_uidvalidities(
            settings.username, settings.folder
        )
        if stored_uid is None and previous_uidvalidities:
            raise RuntimeError(
                "UIDVALIDITY a changé pour le dossier {} ({} → {}). "
                "Synchronisation interrompue pour éviter de perdre des messages.".format(
                    settings.folder,
                    previous_uidvalidities[-1],
                    uidvalidity,
                )
            )
        first_sync = stored_uid is None
        last_uid = stored_uid or 0
        criterion = "ALL" if last_uid == 0 else "UID {}:*".format(last_uid + 1)
        status, data = client.uid("SEARCH", None, criterion)
        if status != "OK":
            raise RuntimeError("La recherche des UID IMAP a échoué.")
        discovered = tuple(uid for uid in _uids(data) if uid > last_uid)
        available = len(discovered)
        if first_sync and initial_mode == "latest":
            if discovered:
                last_uid = max(discovered)
                skipped_on_initialization = len(discovered)
            store.save_imap_last_uid(
                settings.username, settings.folder, uidvalidity, last_uid
            )
            selected = ()
        else:
            selected = discovered[:limit] if limit else discovered
        for uid in selected:
            destination = inbox_path / "imap-{}-{}.eml".format(uidvalidity, uid)
            try:
                if destination.is_file():
                    existing += 1
                else:
                    status, message_data = client.uid("FETCH", str(uid), "(RFC822)")
                    if status != "OK":
                        raise RuntimeError("Le téléchargement IMAP a échoué.")
                    _write_message(destination, _message_bytes(message_data))
                    downloaded += 1
                store.save_imap_last_uid(
                    settings.username, settings.folder, uidvalidity, uid
                )
                last_uid = uid
            except Exception as error:
                errors.append("UID {}: {}".format(uid, _safe_error(error, settings.password)))
                break
        return IMAPSyncReport(
            folder=settings.folder,
            uidvalidity=uidvalidity,
            messages_available=available,
            messages_downloaded=downloaded,
            messages_existing=existing,
            messages_skipped_on_initialization=skipped_on_initialization,
            last_uid=last_uid,
            errors=tuple(errors),
        )
    except Exception as error:
        raise MailDiagnosticError(_safe_error(error, settings.password)) from None
    finally:
        store.close()
        if client is not None:
            try:
                client.logout()
            except Exception:
                pass
