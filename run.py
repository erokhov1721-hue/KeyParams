import os

from app import create_app

app = create_app()


def main():
    """Development by default — the debug reloader that already runs here.

    ``KEYPARAMS_ENV=production`` switches to waitress instead: no debugger
    (its console is remote code execution), no reloader, listening on every
    interface rather than just localhost so a reverse proxy on another
    machine can reach it. One thread pool, not one process per core —
    ``purge_deleted`` runs a delete on every dashboard load and the NER model
    lives in each process's own memory, so more processes means more of both,
    not more capacity.
    """
    if os.environ.get("KEYPARAMS_ENV") == "production":
        from waitress import serve
        host = os.environ.get("KEYPARAMS_HOST", "0.0.0.0")
        port = int(os.environ.get("KEYPARAMS_PORT", "8080"))
        serve(app, host=host, port=port, threads=8)
    else:
        app.run(debug=True)


if __name__ == "__main__":
    main()
