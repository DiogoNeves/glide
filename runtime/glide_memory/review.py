"""Render a verified proposal for conversation or an optional interactive review."""
import argparse
import json
from pathlib import Path
from urllib.parse import quote

from .store import Store, StoreError


def _review_data(store, proposal_id):
    proposal = store._read_proposal(proposal_id)
    loaded = store._load()
    if any(bundle.get("proposal_id") == proposal_id for bundle in loaded["bundles"]):
        raise StoreError("Proposal was already decided; retrieve its receipt")
    for rid, revision in proposal["expected_revisions"].items():
        current = loaded["records"].get(rid)
        if (current["revision"] if current else 0) != revision:
            raise StoreError("Proposal is stale; generate a new proposal before reviewing")
    return {**proposal, "adapter": store.adapter, "vault_name": store.vault.name}


def _text_review(store, data):
    lines = ["**Why this review:** " + data["rationale"], ""]
    for record in data["records"]:
        lines += [f"**{record['title']}**", "", f"AI interpretation · current revision {data['expected_revisions'][record['id']]} · {record['review']}", "", "**Proposed record**", "", record["body"], "", "**Supporting passages**", ""]
        for source in record["sources"]:
            label = source.get("path") or source.get("uri")
            target = quote(str(store.vault / source["path"]), safe="/") if source.get("path") else source["uri"]
            lines += [f"[{label}]({target})" + (" · " + source["locator"] if source.get("locator") else ""), "", "> " + source["quote"].replace("\n", "\n> "), ""]
        if record["claims"]:
            lines += ["**Claims and qualifications**", ""]
            for claim in record["claims"]:
                lines += [f"- {claim['text']} ({claim['type']})" + (" — " + claim["uncertainty"] if claim.get("uncertainty") else "")]
                for source in claim["sources"]:
                    lines += ["", "> " + source["quote"].replace("\n", "\n> "), "", f"Source: {source.get('path') or source.get('uri')}" + (" · " + source["locator"] if source.get("locator") else "")]
            lines.append("")
        if record["relationships"]:
            lines += ["**Why the connections matter**", ""]
            lines += [f"- {r['type']} → {r.get('target_title') or r['target']}: {r['reason']}" for r in record["relationships"]]
            lines.append("")
    lines += ["Reply with confirmation, rejection, or what you would question or adjust. This preview has not applied a change.", "", f"Proposal: `{data['proposal_id']}` · instance: `{data['instance_id']}`", f"Expected revisions: `{json.dumps(data['expected_revisions'], sort_keys=True)}`"]
    return "\n".join(lines) + "\n"


def render_review(store, proposal_id, *, ui=None):
    data = _review_data(store, proposal_id)
    ui = ui or store.review_settings()["review_ui"]
    if ui == "text":
        return _text_review(store, data)
    if ui != "interactive":
        raise StoreError("Review UI must be text or interactive")
    encoded = json.dumps(data, ensure_ascii=False).replace("<", r"\u003c").replace(">", r"\u003e").replace("&", r"\u0026")
    template = Path(__file__).with_suffix('.html').read_text()
    return template.replace('GLIDE_REVIEW_ROOT', 'glide-review-' + proposal_id[:12]).replace('GLIDE_REVIEW_DATA', encoded)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--proposal', required=True)
    parser.add_argument('--ui', choices=['text', 'interactive'], help='Override the configured presentation for this preview only')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = render_review(Store.from_config(args.config), args.proposal, ui=args.ui)
    if args.output:
        args.output.write_text(result)
    else:
        print(result)
