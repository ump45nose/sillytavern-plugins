import argparse
import json
import os


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["serve", "collect", "status", "backup"])
    parser.add_argument("--database", default=os.getenv("SUBSCRIPTIONS_DATABASE", "/data/subscriptions.sqlite"))
    parser.add_argument("--destination")
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn
        from .api import create_app
        from .settings import Settings
        settings = Settings.from_env()
        uvicorn.run(create_app(settings), host=settings.runtime.host, port=settings.runtime.port, access_log=False)
        return
    from .store import Store
    store = Store(args.database)
    if args.command == "collect":
        from .collection import collect
        from .settings import collection_config
        print(json.dumps(collect(store, collection_config())))
    elif args.command == "backup":
        if not args.destination: parser.error("--destination required")
        store.backup(args.destination)
        print(json.dumps({"backed_up": True}))
    else:
        print(json.dumps({"integrity": store.integrity(), "count": store.list()["total"]}))


if __name__ == "__main__": main()
