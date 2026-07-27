"""
Tests de la API de la calculadora.

Fijate un detalle importante: estos tests NO levantan un servidor de verdad.
TestClient de FastAPI llama a la aplicacion directamente en memoria, asi que
corren rapido y no dependen de que haya un puerto libre.
"""

import pytest
from fastapi.testclient import TestClient

import main
from main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Camino feliz: las cuatro operaciones
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "operacion, a, b, esperado",
    [
        ("suma", 2, 3, 5),
        ("suma", -4, 1.5, -2.5),
        ("resta", 10, 4, 6),
        ("resta", 4, 10, -6),
        ("multiplicacion", 6, 7, 42),
        ("multiplicacion", 3, 0, 0),
        ("division", 10, 4, 2.5),
        ("division", -9, 3, -3),
    ],
)
def test_calcula_correctamente(operacion, a, b, esperado):
    respuesta = client.post("/api/calcular", json={"a": a, "b": b, "operacion": operacion})

    assert respuesta.status_code == 200
    assert respuesta.json()["resultado"] == esperado


def test_la_respuesta_incluye_la_expresion_legible():
    respuesta = client.post("/api/calcular", json={"a": 8, "b": 2, "operacion": "division"})

    cuerpo = respuesta.json()
    assert cuerpo["expresion"] == "8.0 / 2.0 = 4.0"
    assert cuerpo["simbolo"] == "/"


# ---------------------------------------------------------------------------
# Casos borde: aca es donde se separa el codigo serio del codigo de juguete
# ---------------------------------------------------------------------------

def test_division_por_cero_devuelve_400_y_no_revienta():
    respuesta = client.post("/api/calcular", json={"a": 5, "b": 0, "operacion": "division"})

    assert respuesta.status_code == 400
    assert "cero" in respuesta.json()["detail"].lower()


def test_operacion_desconocida_devuelve_422():
    # 422 lo genera Pydantic solo, porque el campo esta tipado como Literal.
    respuesta = client.post("/api/calcular", json={"a": 1, "b": 2, "operacion": "potencia"})

    assert respuesta.status_code == 422


def test_valor_no_numerico_devuelve_422():
    respuesta = client.post("/api/calcular", json={"a": "hola", "b": 2, "operacion": "suma"})

    assert respuesta.status_code == 422


# ---------------------------------------------------------------------------
# Limites de los numeros de la computadora
# ---------------------------------------------------------------------------
# Un float de 64 bits llega hasta ~1.8e308. Pasado ese punto el resultado es
# "infinito", y ACA esta el problema: infinito NO EXISTE en JSON. El estandar
# no lo contempla. Si dejas que llegue al serializador, la API revienta con un
# 500 — o sea, culpa al servidor de un dato que mando el cliente.

@pytest.mark.parametrize(
    "a, b, operacion",
    [
        (1e308, 10, "multiplicacion"),      # overflow hacia +infinito
        (-1e308, 10, "multiplicacion"),     # overflow hacia -infinito
        (1, 5e-324, "division"),            # dividir por algo diminuto tambien desborda
    ],
)
def test_resultado_fuera_de_rango_devuelve_400_no_500(a, b, operacion):
    respuesta = client.post("/api/calcular", json={"a": a, "b": b, "operacion": operacion})

    assert respuesta.status_code == 400
    assert "rango" in respuesta.json()["detail"].lower()


@pytest.mark.parametrize(
    "literal_a",
    [
        "1e400",     # numero JSON tan grande que al parsearlo ya es infinito
        '"inf"',     # Pydantic en modo lax acepta strings numericas...
        '"nan"',     # ...y float("nan") es "valido" en Python
        '"-inf"',
    ],
)
def test_operando_no_finito_devuelve_422(literal_a):
    """
    Si el dato de ENTRADA ya es infinito o NaN, es un problema de validacion
    (422), no de calculo. Se rechaza antes de hacer la cuenta.

    Fijate que mandamos el cuerpo como TEXTO CRUDO con content=, no con json=.
    ¿Por que? Porque json= usa json.dumps de Python, que se NIEGA a serializar
    infinito. Asimetria curiosa del modulo json:
        json.dumps(float("inf"))  -> ValueError
        json.loads("1e400")       -> inf, sin una queja
    O sea: Python no lo escribe, pero lo lee feliz. Y un cliente cualquiera
    (curl, otro lenguaje) SI puede mandar ese texto. Por eso lo probamos asi.
    """
    cuerpo = f'{{"a": {literal_a}, "b": 1, "operacion": "suma"}}'

    respuesta = client.post(
        "/api/calcular",
        content=cuerpo,
        headers={"Content-Type": "application/json"},
    )

    assert respuesta.status_code == 422


def test_una_cuenta_grande_pero_valida_sigue_funcionando():
    # Que no nos pasemos de celosos: 1e308 es enorme pero es finito.
    respuesta = client.post("/api/calcular", json={"a": 1e308, "b": 1, "operacion": "suma"})

    assert respuesta.status_code == 200
    assert respuesta.json()["resultado"] == 1e308


def test_falta_un_campo_devuelve_422():
    respuesta = client.post("/api/calcular", json={"a": 1, "operacion": "suma"})

    assert respuesta.status_code == 422


# ---------------------------------------------------------------------------
# CORS — ahora que el front vive en otro servidor, esto es de verdad
# ---------------------------------------------------------------------------
# Antes de mandar un POST con Content-Type: application/json a otro origen,
# el navegador manda solo un OPTIONS preguntando "¿me dejas?". Eso se llama
# PREFLIGHT. Si la API no contesta bien ese OPTIONS, tu POST nunca sale.
# El usuario ve un error de CORS en la consola y jura que la API esta caida.

def test_preflight_desde_el_front_permitido():
    respuesta = client.options(
        "/api/calcular",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert respuesta.status_code == 200
    assert respuesta.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_preflight_desde_127_0_0_1_tambien_permitido():
    # localhost y 127.0.0.1 son ORIGENES DISTINTOS para el navegador, aunque
    # sean la misma maquina. Si solo permitis uno, el otro falla.
    respuesta = client.options(
        "/api/calcular",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert respuesta.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"


def test_un_origen_desconocido_no_recibe_permiso():
    respuesta = client.options(
        "/api/calcular",
        headers={
            "Origin": "http://sitio-malicioso.com",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert "access-control-allow-origin" not in respuesta.headers


def test_los_errores_400_llevan_headers_de_cors():
    # ESTE TEST ES IMPORTANTE. Si una respuesta de error no lleva el header de
    # CORS, el navegador la tira a la basura antes de que el front la vea, y el
    # usuario recibe "no se pudo contactar a la API" cuando en realidad la API
    # contesto perfecto. Es el bug mas confuso de debuggear que existe.
    respuesta = client.post(
        "/api/calcular",
        json={"a": 5, "b": 0, "operacion": "division"},
        headers={"Origin": "http://localhost:3000"},
    )

    assert respuesta.status_code == 400
    assert respuesta.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_los_errores_422_llevan_headers_de_cors():
    respuesta = client.post(
        "/api/calcular",
        json={"a": "hola", "b": 1, "operacion": "suma"},
        headers={"Origin": "http://localhost:3000"},
    )

    assert respuesta.status_code == 422
    assert respuesta.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_un_error_inesperado_devuelve_json_con_cors_y_no_texto_plano(monkeypatch):
    # Simulamos un bug nuestro: hacemos que la suma explote.
    # Sin la red de seguridad, Starlette contesta 500 en text/plain y SIN
    # headers de CORS — el front no ve nada y miente sobre la causa.
    def bomba(a, b):
        raise RuntimeError("bug inventado a proposito para este test")

    monkeypatch.setitem(main.OPERACIONES, "suma", ("+", bomba))

    respuesta = client.post(
        "/api/calcular",
        json={"a": 1, "b": 2, "operacion": "suma"},
        headers={"Origin": "http://localhost:3000"},
    )

    assert respuesta.status_code == 500
    assert respuesta.headers["content-type"].startswith("application/json")
    assert respuesta.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "detail" in respuesta.json()


def test_la_api_ya_no_sirve_el_front():
    # El backend ahora es SOLO una API. El HTML lo sirve otro servidor.
    respuesta = client.get("/")

    assert respuesta.status_code == 404


def test_healthcheck():
    respuesta = client.get("/api/salud")

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "ok"
