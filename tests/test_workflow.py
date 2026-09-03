from pathlib import Path


WORKFLOW = Path(".github/workflows/sync_render.yml")


def test_workflow_has_safe_garmin_token_lifecycle():
    workflow = WORKFLOW.read_text()

    assert "workflow_dispatch:" in workflow
    assert "contents: write" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "GARMIN_TOKEN_KEY" in workflow
    assert "if: always()" in workflow
    assert "STRAVA_CLIENT_SECRET" not in workflow
    assert "STRAVA_REFRESH_TOKEN" not in workflow
    assert "git commit -a" not in workflow


def test_workflow_serializes_sync_and_stages_only_generated_files():
    workflow = WORKFLOW.read_text()

    assert "group: running-sync-${{ github.ref }}" in workflow
    assert "data/garmin_tokens.enc" in workflow
    assert "data/running_records_garmin_sync.json" in workflow
    assert "data/running_records_combined.json" in workflow
    assert "data/running.csv" in workflow
    assert "running.svg" in workflow
    assert "git add data/*.csv *.svg" not in workflow
