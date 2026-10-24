from fastapi.testclient import TestClient

from server.main import app


def test_blackboard_page_and_stylesheet():
    with TestClient(app) as client:
        response = client.get("/blackboard")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert response.template.name == "blackboard.html"
        assert "<h1>Blackboard</h1>" in response.text
        assert 'id="download-report" type="button" disabled' in response.text
        assert "Descargar informe Word" in response.text

        stylesheet_url = str(app.url_path_for("web_static", path="styles.css"))
        assert stylesheet_url in response.text
        stylesheet = client.get(stylesheet_url)
        assert stylesheet.status_code == 200
        assert stylesheet.headers["content-type"].startswith("text/css")

        script_url = str(app.url_path_for("web_static", path="blackboard.js"))
        assert script_url in response.text
        assert client.get(script_url).status_code == 200


def test_run_id_is_preserved_and_escaped_in_the_lookup_form():
    with TestClient(app) as client:
        response = client.get("/blackboard", params={"run_id": '\"><script>alert(1)</script>'})
        assert '<script>alert(1)</script>' not in response.text
        assert '&lt;script&gt;alert(1)&lt;/script&gt;' in response.text
