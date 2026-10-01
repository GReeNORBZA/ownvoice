from pathlib import Path

from ownvoice.config import load_config
from ownvoice.errors import DiagnosticError, ExitCode
from ownvoice.ingest import pst
from ownvoice.layout import Layout
from ownvoice.qual import chunk


def run(args):
    if args.chunks:
        manifest_path = Path(args.chunks).expanduser().resolve()
        if not manifest_path.is_file():
            raise chunk.problem(
                "clean qual chunks",
                manifest_path,
                "manifest not found",
                "an existing manifest",
                "supply the manifest written by qual chunk",
            )
        value = chunk.load(manifest_path)
        paths = chunk.listed_paths(manifest_path, value)
        for path in paths:
            try:
                size = path.stat().st_size if path.exists() else 0
                path.unlink(missing_ok=True)
            except OSError as exc:
                raise DiagnosticError(
                    "clean qual chunks",
                    path,
                    str(exc),
                    "a removable listed file",
                    exc,
                    "restore file permissions and retry cleanup",
                    exit_code=ExitCode.DEPENDENCY,
                ) from exc
            print(f"clean qual chunks [{path}]: removed {size} bytes")
        return 0
    config, _ = load_config(args.config)
    work = Path(config["paths"]["work_dir"])
    if args.all or args.extracted == "all":
        paths = pst.retained(work)
    else:
        label = args.extracted
        if label not in {s["label"] for s in config["source"]}:
            raise DiagnosticError(
                "clean extracted PST",
                label,
                "unknown source label",
                "a configured source label",
                None,
                "use a configured label or clean --all",
            )
        paths = [Layout(work).source_paths(label)["extract"]]
    for path in paths:
        count = pst.size(path) if path.exists() else 0
        pst.remove(path)
        print(f"clean extracted PST [{path}]: removed {count} bytes")
    return 0
