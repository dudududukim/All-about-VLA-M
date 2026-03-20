import os
import sys
import json
import time
import pytz
import urllib.parse
import urllib.request
from datetime import datetime

from utils import get_daily_papers_by_keyword_with_retries, generate_table, back_up_files, \
    restore_files, remove_backups, get_daily_date


eastern_timezone = pytz.timezone('US/Eastern')

# NOTE: arXiv API seems to sometimes return an unexpected empty list.

current_date = datetime.now(eastern_timezone).strftime("%Y-%m-%d")
# get last update date from README.md
with open("README.md", "r") as f:
    while True:
        line = f.readline()
        if "Last update:" in line: break
    last_update_date = line.split(": ")[1].strip()
    if last_update_date == current_date:
        sys.exit("Already updated today!")

keywords = ["Vision Language Action", "robot manipulation", "Vision Language Model", "world model", "diffusion policy", "reinforcement learning robot"]

max_result = 50     # maximum query results from arXiv API for each keyword
issues_result = 15  # maximum papers to be included in the issue

# all columns: Title, Authors, Abstract, Link, Tags, Comment, Date
column_names = ["Title", "Link", "Abstract", "Date", "Comment"]


def summarize_abstract(abstract: str) -> str:
    """Call GitHub Models API for a one-sentence summary. Returns '' on any failure."""
    try:
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            return ""
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "Summarize the following ML paper abstract in one concise sentence."},
                {"role": "user", "content": abstract}
            ],
            "max_tokens": 80
        }
        req = urllib.request.Request(
            "https://models.inference.ai.azure.com/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"summarize_abstract failed: {e}")
        return ""


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def generate_html(all_papers: dict, updated: str, github_repository: str) -> str:
    """Generate docs/index.html from {keyword: [paper_dict]} where paper_dict has Title, Link, Date, Comment, Summary."""
    parts = github_repository.split("/") if "/" in github_repository else ["", ""]
    github_username, repo_name = parts[0], parts[1] if len(parts) > 1 else ""
    hits_url = f"https://{github_username}.github.io/{repo_name}"
    hits_badge = f"https://hits.seeyoufarm.com/api/count/incr/badge.svg?url={urllib.parse.quote(hits_url, safe='')}&title=Visitors"

    sections_html = ""
    for keyword, papers in all_papers.items():
        rows = ""
        for p in papers:
            title = _html_escape(p.get("Title", ""))
            link = _html_escape(p.get("Link", ""))
            date = _html_escape(p.get("Date", "").split("T")[0])
            comment = _html_escape(p.get("Comment", ""))
            summary = _html_escape(p.get("Summary", ""))
            rows += f"""
        <tr>
          <td><a href="{link}" target="_blank">{title}</a></td>
          <td>{date}</td>
          <td>{comment}</td>
          <td>{summary}</td>
        </tr>"""

        keyword_id = keyword.replace(" ", "-").lower()
        sections_html += f"""
  <section id="{keyword_id}">
    <h2>{_html_escape(keyword)}</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Title</th><th>Date</th><th>Comment</th><th>Summary</th></tr></thead>
        <tbody>{rows}
        </tbody>
      </table>
    </div>
  </section>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Daily VLA Papers</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f8fa; color: #24292f; line-height: 1.6; }}
    header {{ background: #0d1117; color: #e6edf3; padding: 2rem; text-align: center; }}
    header h1 {{ font-size: 1.8rem; margin-bottom: 0.4rem; }}
    header .meta {{ font-size: 0.85rem; color: #8b949e; }}
    header img {{ margin-top: 0.6rem; }}
    .search-wrap {{ max-width: 860px; margin: 1.5rem auto; padding: 0 1rem; }}
    #search {{ width: 100%; padding: 0.6rem 1rem; font-size: 1rem; border: 1px solid #d0d7de; border-radius: 6px; outline: none; }}
    #search:focus {{ border-color: #0969da; box-shadow: 0 0 0 3px rgba(9,105,218,.15); }}
    section {{ max-width: 860px; margin: 0 auto 2rem; padding: 0 1rem; }}
    section h2 {{ font-size: 1.15rem; margin-bottom: 0.75rem; padding-bottom: 0.4rem; border-bottom: 2px solid #d0d7de; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; background: #fff; border-radius: 6px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
    th {{ background: #f0f2f5; text-align: left; padding: 0.55rem 0.75rem; font-weight: 600; white-space: nowrap; }}
    td {{ padding: 0.5rem 0.75rem; border-top: 1px solid #eaecef; vertical-align: top; }}
    td:nth-child(2) {{ white-space: nowrap; }}
    a {{ color: #0969da; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    tr.hidden {{ display: none; }}
  </style>
</head>
<body>
  <header>
    <h1>Daily VLA &amp; Robotics Papers</h1>
    <div class="meta">Last updated: {_html_escape(updated)}</div>
    <img src="{_html_escape(hits_badge)}" alt="Visitors" />
  </header>

  <div class="search-wrap">
    <input id="search" type="text" placeholder="Search by title or summary…" />
  </div>

{sections_html}

  <script>
    const input = document.getElementById('search');
    input.addEventListener('input', function() {{
      const q = this.value.toLowerCase();
      document.querySelectorAll('tbody tr').forEach(function(row) {{
        const title = (row.cells[0] ? row.cells[0].textContent : '').toLowerCase();
        const summary = (row.cells[3] ? row.cells[3].textContent : '').toLowerCase();
        row.classList.toggle('hidden', q && !title.includes(q) && !summary.includes(q));
      }});
    }});
  </script>
</body>
</html>"""



back_up_files()  # back up README.md and ISSUE_TEMPLATE.md

try:
    # write to README.md
    f_rm = open("README.md", "w")
    f_rm.write("# All about VLA-M\n\n")
    f_rm.write(
        "📄 **[Browse papers → GitHub Pages](https://dudududukim.github.io/All-about-VLA-M)**\n\n"
        "Papers on Vision-Language-Action models, robot manipulation, diffusion policy, and related topics "
        "are fetched daily from arXiv. "
        "Each paper is summarized in one sentence by an LLM, and the full list is searchable on the GitHub Pages site above.\n\n"
        "---\n\n"
        "*Based on [DailyArxiv](https://github.com/Ed1sonChen/DailyArxiv) by Ed1sonChen.*\n\n"
        "Last update: {0}\n\n".format(current_date)
    )

    # write to ISSUE_TEMPLATE.md
    f_is = open(".github/ISSUE_TEMPLATE.md", "w")
    f_is.write("---\n")
    f_is.write("title: Latest {0} Papers - {1}\n".format(issues_result, get_daily_date()))
    f_is.write("labels: documentation\n")
    f_is.write("---\n")
    f_is.write("**Please check the [Github](https://github.com/Ed1sonChen/DailyArxiv) page for a better reading experience and more papers.**\n\n")

    all_papers_for_html = {}  # {keyword: [paper_dict_with_summary]}

    for keyword in keywords:
        try:
            f_is.write("## {0}\n".format(keyword))
            if len(keyword.split()) == 1: link = "AND"
            else: link = "OR"
            papers = get_daily_papers_by_keyword_with_retries(keyword, column_names, max_result, link)
            if papers is None:
                print("Failed to get papers for keyword: {0}".format(keyword))
                continue

            # LLM summaries — one per paper, with rate limiting
            papers_with_summary = []
            for paper in papers:
                summary = summarize_abstract(paper.get("Abstract", ""))
                time.sleep(1)  # rate limit: 1 s between LLM calls
                papers_with_summary.append({**paper, "Summary": summary})

            all_papers_for_html[keyword] = papers_with_summary

            is_table = generate_table(papers[:issues_result], ignore_keys=["Abstract"])
            f_is.write(is_table)
            f_is.write("\n\n")
            time.sleep(5)  # avoid being blocked by arXiv API
        except Exception as e:
            print("Error processing keyword {0}: {1}".format(keyword, e))
            continue

    f_rm.close()
    f_is.close()

    # generate docs/index.html
    os.makedirs("docs", exist_ok=True)
    github_repository = os.environ.get("GITHUB_REPOSITORY", "/")
    html_content = generate_html(all_papers_for_html, current_date, github_repository)
    with open("docs/index.html", "w", encoding="utf-8") as f_html:
        f_html.write(html_content)

    remove_backups()

except Exception:
    restore_files()
    raise
