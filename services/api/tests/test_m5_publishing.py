"""Comprehensive Test Battery for Milestone 5: Publishing Engine, Feeds Architecture,
Verification, and Prove-Then-Close Gap Lifecycle.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from datetime import UTC, datetime
from uuid import uuid4

import psycopg2
import pytest
from fastapi.testclient import TestClient

from services.api.app.crypto import (
    decrypt_credentials,
    encrypt_credentials,
    get_encryption_key,
    mask_credentials,
)
from services.api.app.db import engine
from services.api.app.main import app
from services.api.tests.conftest import get_admin_dsn
from services.workers.app.feeds_builder import FeedsBuilder
from services.workers.app.publisher import (
    _extract_meta_from_html,
    run_publisher,
    verify_publication,
)
from services.workers.app.wordpress_client import (
    build_article_jsonld,
    markdown_to_html,
    slugify,
)
from services.workers.app.worker import compute_rollup_for_day


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c
        assert c.portal is not None
        c.portal.call(engine.dispose)


def _token(client: TestClient, email: str = "user_a@test.com") -> str:
    res = client.post("/api/v1/auth/dev-login", json={"email": email})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def m5_site(client: TestClient) -> Generator[str, None, None]:
    """A fresh website for M5 publishing testing."""
    token = _token(client)
    res = client.post(
        "/api/v1/clients",
        headers=_auth(token),
        json={
            "name": f"Publishing Site {uuid4().hex[:6]}",
            "primary_domain": f"m5-{uuid4().hex[:8]}.example.com",
            "country": "US",
        },
    )
    assert res.status_code == 201, res.text
    client_id = res.json()["id"]

    # Seed brand profile & feeds_sites
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO brand_profiles (client_id, voice, positioning, proof_points, banned_claims, theme_css)
        VALUES (%s, 'authoritative', 'Enterprise AI Search Optimization',
                '["Cites 100+ sources", "500 enterprise customers"]'::jsonb,
                ARRAY['banned cheap claims'], 'body { background: #000; color: #fff; }')
        ON CONFLICT (client_id) DO UPDATE
        SET voice = EXCLUDED.voice, positioning = EXCLUDED.positioning;

        INSERT INTO feeds_sites (client_id, mount_path, custom_domain)
        VALUES (%s, '/feeds', 'feeds.example.com')
        ON CONFLICT (client_id) DO NOTHING;
        """,
        (client_id, client_id),
    )
    conn.close()

    yield client_id

    # Cleanup
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DELETE FROM clients WHERE id = %s", (client_id,))
    conn.close()


# ───────────── 1. Cryptography Unit Tests ─────────────

def test_crypto_aes256_gcm_roundtrip() -> None:
    key = get_encryption_key()
    assert len(key) == 32

    payload = {
        "endpoint": "https://cms.acme.com",
        "username": "editor_user",
        "app_password": "xxxx-yyyy-zzzz-1234",
        "api_key": "sec_999888777",
    }

    encrypted_bytes = encrypt_credentials(payload)
    assert isinstance(encrypted_bytes, bytes)
    assert len(encrypted_bytes) > 28
    assert b"xxxx-yyyy-zzzz-1234" not in encrypted_bytes

    decrypted = decrypt_credentials(encrypted_bytes)
    assert decrypted == payload

    # Tampered ciphertext fails authentication
    tampered = bytearray(encrypted_bytes)
    tampered[-1] ^= 0xFF
    with pytest.raises(ValueError, match="Failed to decrypt"):
        decrypt_credentials(bytes(tampered))

    # Credential masking
    masked = mask_credentials(payload)
    assert masked["endpoint"] == "https://cms.acme.com"
    assert masked["username"] == "editor_user"
    assert "xxxx" not in masked["app_password"]
    assert "••••••••" in masked["app_password"]
    assert "999888777" not in masked["api_key"]


# ───────────── 2. WordPress Client & Markdown Helpers ─────────────

def test_wordpress_client_helpers() -> None:
    md = "# Main Header\n\nThis is a **bold** paragraph with [link](https://example.com).\n\n- Point 1\n- Point 2\n\n> Important quote"
    html_output = markdown_to_html(md)

    assert "<h1>Main Header</h1>" in html_output
    assert "<strong>bold</strong>" in html_output
    assert '<a href="https://example.com">link</a>' in html_output
    assert "<li>Point 1</li>" in html_output
    assert "<blockquote><p>Important quote</p></blockquote>" in html_output

    assert slugify("Enterprise AI & Search 2026!") == "enterprise-ai-search-2026"

    jsonld = build_article_jsonld(
        title="AI Search Optimization",
        canonical_url="https://example.com/ai-search-optimization",
        brand_name="Acme Corp",
    )
    assert jsonld["@context"] == "https://schema.org"
    assert jsonld["@type"] == "Article"
    assert jsonld["headline"] == "AI Search Optimization"
    assert jsonld["publisher"]["name"] == "Acme Corp"


def test_html_meta_extractor() -> None:
    raw_html = """<!DOCTYPE html>
    <html>
      <head>
        <title>Guide to GEO | Footnote</title>
        <link rel="canonical" href="https://example.com/geo-guide" />
        <script type="application/ld+json">
          {"@context": "https://schema.org", "@type": "Article", "headline": "Guide to GEO"}
        </script>
      </head>
      <body><h1>Content</h1></body>
    </html>"""

    title, canonical, jsonld_valid = _extract_meta_from_html(raw_html)
    assert title == "Guide to GEO | Footnote"
    assert canonical == "https://example.com/geo-guide"
    assert jsonld_valid is True


# ───────────── 3. Publish Targets API ─────────────

def test_publish_targets_crud_and_test(client: TestClient, m5_site: str) -> None:
    token = _token(client)
    headers = _auth(token)
    cid = m5_site

    # 1. Create WordPress Target
    create_res = client.post(
        f"/api/v1/clients/{cid}/publish-targets",
        headers=headers,
        json={
            "name": "Production WordPress",
            "kind": "wordpress",
            "is_default": True,
            "config": {
                "endpoint": "https://blog.example.com",
                "username": "wp_editor",
                "app_password": "super-secret-password-1234",
            },
        },
    )
    assert create_res.status_code == 201, create_res.text
    target_data = create_res.json()
    target_id = target_data["id"]
    assert target_data["name"] == "Production WordPress"
    assert target_data["kind"] == "wordpress"
    assert target_data["is_default"] is True
    # Verify masked credentials
    assert "super-secret" not in target_data["config"]["app_password"]
    assert "••••••••" in target_data["config"]["app_password"]

    # Verify ciphertext in DB is encrypted
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT config_enc FROM publish_targets WHERE id = %s", (target_id,))
    enc_bytes = bytes(cur.fetchone()[0])
    conn.close()
    assert b"super-secret-password-1234" not in enc_bytes
    assert decrypt_credentials(enc_bytes)["app_password"] == "super-secret-password-1234"

    # 2. List Targets
    list_res = client.get(f"/api/v1/clients/{cid}/publish-targets", headers=headers)
    assert list_res.status_code == 200
    targets = list_res.json()
    assert len(targets) >= 1
    assert any(t["id"] == target_id for t in targets)

    # 3. Create Feeds Target
    feeds_res = client.post(
        f"/api/v1/clients/{cid}/publish-targets",
        headers=headers,
        json={
            "name": "Static Edge Feeds",
            "kind": "feeds",
            "is_default": False,
            "config": {"mount_path": "/feeds", "custom_domain": "feeds.example.com"},
        },
    )
    assert feeds_res.status_code == 201
    feeds_target_id = feeds_res.json()["id"]

    # 4. Test Feeds connection
    test_res = client.post(f"/api/v1/clients/{cid}/publish-targets/{feeds_target_id}/test", headers=headers)
    assert test_res.status_code == 200
    test_body = test_res.json()
    assert test_body["status"] == "success"
    assert "Feeds static builder engine configured" in test_body["detail"]

    # 5. Delete WordPress Target
    del_res = client.delete(f"/api/v1/clients/{cid}/publish-targets/{target_id}", headers=headers)
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"


# ───────────── 4. Feeds Static Site Builder ─────────────

def test_feeds_builder_execution(client: TestClient, m5_site: str) -> None:
    cid = m5_site

    # Seed a published content item with current version
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    cur = conn.cursor()
    item_id = str(uuid4())
    version_id = str(uuid4())

    cur.execute(
        """
        INSERT INTO content_items (id, client_id, status, published_at)
        VALUES (%s, %s, 'published', now());

        INSERT INTO content_versions (id, content_item_id, client_id, version_no, title, body_md, word_count, reading_time_min, author_kind)
        VALUES (%s, %s, %s, 1, 'The Ultimate Guide to Generative Engine Optimization',
                '# The Ultimate Guide\n\nAnswer in first sentence: GEO is the practice of optimizing content for AI engines.\n\n- Rule 1: Ground facts\n- Rule 2: Cite sources',
                450, 2.5, 'agent');

        UPDATE content_items SET current_version_id = %s WHERE id = %s;
        """,
        (item_id, cid, version_id, item_id, cid, version_id, item_id),
    )
    conn.close()

    builder = FeedsBuilder(cid)
    summary = client.portal.call(builder.build)

    assert summary["pages_count"] >= 1
    assert summary["hub_url"].endswith("/feeds/index.html")
    assert summary["sitemap_url"].endswith("/feeds/sitemap.xml")

    # Verify generated static files
    out_dir = builder.output_dir
    index_file = out_dir / "index.html"
    sitemap_file = out_dir / "sitemap.xml"
    article_file = out_dir / "the-ultimate-guide-to-generative-engine-optimization.html"

    assert index_file.exists()
    assert sitemap_file.exists()
    assert article_file.exists()

    article_html = article_file.read_text(encoding="utf-8")
    assert "The Ultimate Guide to Generative Engine Optimization" in article_html
    assert 'rel="canonical"' in article_html
    assert 'application/ld+json' in article_html
    assert "schema.org" in article_html.lower()


# ───────────── 5. Hard Approval Gate & Publishing Execution ─────────────

def test_hard_approval_gate_and_publish_flow(client: TestClient, m5_site: str) -> None:
    token = _token(client)
    headers = _auth(token)
    cid = m5_site

    # 1. Create a prompt and an open gap
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    cur = conn.cursor()
    prompt_id = str(uuid4())
    gap_id = str(uuid4())
    item_id = str(uuid4())
    version_id = str(uuid4())

    cur.execute(
        """
        INSERT INTO prompts (id, client_id, text, is_active)
        VALUES (%s, %s, 'What is the top enterprise GEO software?', true);

        INSERT INTO gaps (id, client_id, prompt_id, gap_type, status, details)
        VALUES (%s, %s, %s, 'absent', 'open', '{"detected_by": "test"}'::jsonb);

        INSERT INTO content_items (id, client_id, status)
        VALUES (%s, %s, 'in_review');

        INSERT INTO content_versions (id, content_item_id, client_id, version_no, title, body_md, word_count, author_kind)
        VALUES (%s, %s, %s, 1, 'Comparing Leading GEO Platforms in 2026',
                '# Leading Platforms\n\nAcme leads enterprise GEO with complete audit coverage.', 300, 'writer');

        UPDATE content_items SET current_version_id = %s WHERE id = %s;

        INSERT INTO content_prompt_map (content_item_id, prompt_id)
        VALUES (%s, %s);
        """,
        (prompt_id, cid, gap_id, cid, prompt_id, item_id, cid, version_id, item_id, cid, version_id, item_id, item_id, prompt_id),
    )
    conn.close()

    # 2. HARD GATE TEST: Attempting publish on unapproved version must return HTTP 400
    publish_unapproved = client.post(
        f"/api/v1/clients/{cid}/content-items/{item_id}/publish",
        headers=headers,
        json={"post_status": "publish"},
    )
    assert publish_unapproved.status_code == 400
    assert "approval gate" in publish_unapproved.json()["detail"].lower()

    # 3. Approve the version
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO approvals (client_id, subject_type, subject_id, reviewer_id, status, decided_at)
        VALUES (%s, 'version', %s, (SELECT id FROM auth.users LIMIT 1), 'approved', now());

        UPDATE content_items SET status = 'approved' WHERE id = %s;
        """,
        (cid, version_id, item_id),
    )
    conn.close()

    # 4. Now publish succeeds
    publish_approved = client.post(
        f"/api/v1/clients/{cid}/content-items/{item_id}/publish",
        headers=headers,
        json={"post_status": "publish"},
    )
    assert publish_approved.status_code == 200, publish_approved.text
    pub_data = publish_approved.json()
    assert pub_data["status"] == "running"
    assert pub_data["publication_id"] is not None


# ───────────── 6. Post-Publish Verification & Prove-Then-Close Gap ─────────────

def test_post_publish_verification_and_prove_then_close(client: TestClient, m5_site: str) -> None:
    cid = m5_site

    # Seed approved item, version, prompt, and gap
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    cur = conn.cursor()
    prompt_id = str(uuid4())
    gap_id = str(uuid4())
    item_id = str(uuid4())
    version_id = str(uuid4())

    cur.execute(
        """
        INSERT INTO prompts (id, client_id, text, is_active)
        VALUES (%s, %s, 'Best enterprise generative engine optimization tools', true);

        INSERT INTO gaps (id, client_id, prompt_id, gap_type, status)
        VALUES (%s, %s, %s, 'absent', 'in_progress');

        INSERT INTO content_items (id, client_id, status)
        VALUES (%s, %s, 'approved');

        INSERT INTO content_versions (id, content_item_id, client_id, version_no, title, body_md, author_kind)
        VALUES (%s, %s, %s, 1, 'Proven Enterprise GEO Best Practices',
                '# Proven Best Practices\n\nDirect citations drive 3x AI search visibility.', 'editor');

        UPDATE content_items SET current_version_id = %s WHERE id = %s;

        INSERT INTO content_prompt_map (content_item_id, prompt_id)
        VALUES (%s, %s);

        INSERT INTO approvals (client_id, subject_type, subject_id, reviewer_id, status, decided_at)
        VALUES (%s, 'version', %s, (SELECT id FROM auth.users LIMIT 1), 'approved', now());
        """,
        (prompt_id, cid, gap_id, cid, prompt_id, item_id, cid, version_id, item_id, cid, version_id, item_id, item_id, prompt_id, cid, version_id),
    )
    conn.close()

    # 1. Run Publisher Worker
    pub_res = client.portal.call(run_publisher, {"verify_immediately": True}, item_id, cid)
    assert pub_res["status"] == "published"
    live_url = pub_res["url"]
    assert live_url is not None

    # 2. Run Verification Worker
    verify_res = client.portal.call(verify_publication, {}, cid, item_id, live_url)
    assert verify_res["is_live"] is True

    # 3. PROVE-THEN-CLOSE CHECK: Verify gap is 'verified_published', NOT 'won'
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT status, published_content_id, verified_at, closed_at FROM gaps WHERE id = %s", (gap_id,))
    row = cur.fetchone()
    assert row[0] == "verified_published"
    assert str(row[1]) == item_id
    assert row[2] is not None
    assert row[3] is None  # NOT closed to 'won' yet!

    # 4. PROVE-THEN-CLOSE CLOSURE: Simulate collection pass citing the brand on this prompt today
    today_str = datetime.now(UTC).date().isoformat()
    answer_id = str(uuid4())
    cur.execute(
        """
        INSERT INTO answers (id, client_id, prompt_id, engine, mode, run_index, status, collected_at, raw_json)
        VALUES (%s, %s, %s, 'chatgpt', 'api', 0, 'succeeded', now(), '{"test": true}'::jsonb);

        INSERT INTO brand_mentions (answer_id, client_id, entity_kind)
        VALUES (%s, %s, 'brand');
        """,
        (answer_id, cid, prompt_id, answer_id, cid),
    )

    # 5. Nightly rollup verifies proof and transitions gap to 'won'
    rollup_stats = client.portal.call(compute_rollup_for_day, today_str)
    assert rollup_stats.get("closed_proved_gaps", 0) >= 1

    # Check gap in DB is now 'won' with closed_at set
    cur.execute("SELECT status, closed_at, details FROM gaps WHERE id = %s", (gap_id,))
    final_gap = cur.fetchone()
    conn.close()

    assert final_gap[0] == "won"
    assert final_gap[1] is not None
    assert final_gap[2].get("closed_by_collection_day") == today_str
