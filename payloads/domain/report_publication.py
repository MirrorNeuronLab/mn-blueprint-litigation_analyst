"""Select the reviewed reports exposed through the runtime's download contract."""

from mn_sdk.blueprint.outputs import publish_files
from mn_sdk_common.publication import ArtifactWrite

from .conversation_sources import REPORTS


def publish_review_files(context):
    names = [*REPORTS, "review_index.json"]
    # The stock block worker delivers this declared publication to the configured
    # output directory and advertises its exports to Core. Writing into the run
    # store alone does not constitute a delivered customer result.
    optional = ["data/chat-summary.json", "web_ui.json"]
    web = context.store.path("web")
    if web.is_dir():
        optional.extend(p.relative_to(context.store.run_dir).as_posix()
                        for p in sorted(web.rglob("*")) if p.is_file())
    names.extend(name for name in optional if context.store.path(name).is_file())
    return publish_files(
        context,
        [
            ArtifactWrite(
                name,
                name,
                context.store.path(name).read_bytes(),
                kind="markdown" if name.endswith(".md") else "json" if name.endswith(".json") else "file",
                authoritative=name not in optional,
                required=name not in optional,
                mode=0o644,
            )
            for name in names
        ],
        name="litigation-review",
    )
