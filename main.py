"""
API de calculadora — FastAPI, sin base de datos, sin estado.

Este servidor es SOLO una API. No sabe nada de HTML, de CSS ni de botones.
Recibe JSON, devuelve JSON. El front vive en otra carpeta y en otro puerto,
y es un programa completamente distinto.

La idea es que esto sea LEIBLE, no impresionante. Cada bloque esta comentado
explicando el POR QUE, no el que (el que ya lo dice el codigo).

Para levantarla, parado en backend/:
    uvicorn main:app --reload --port 8000

Documentacion interactiva: http://127.0.0.1:8000/docs
"""

import math
import os
import traceback
from collections.abc import Callable
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

app = FastAPI(
    title="Calculadora API",
    description="API didactica de 4 operaciones. Sin persistencia, sin estado.",
    version="2.0.0",
)

# ---------------------------------------------------------------------------
# Red de seguridad para errores inesperados
# ---------------------------------------------------------------------------
# Si una excepcion nuestra se escapa sin atrapar, Starlette la maneja en un
# middleware que esta POR FUERA del de CORS. Resultado: contesta un 500 en
# text/plain y SIN headers de CORS.
#
# Y eso produce el bug mas confuso que existe: el navegador descarta esa
# respuesta por no tener permiso, el fetch del front falla con "Failed to
# fetch", y el usuario lee "no se pudo contactar a la API" — mientras el log
# del servidor muestra el pedido entrando y saliendo. Los dos parecen tener
# razon y nadie encuentra el problema.
#
# Este middleware atrapa cualquier excepcion y contesta un 500 en JSON. Como
# esta POR DENTRO del de CORS, la respuesta sale con los headers puestos y el
# front puede leerla y mostrar algo util.
@app.middleware("http")
async def red_de_seguridad(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:
        # El detalle completo va al log del servidor, donde lo ve el que
        # programa. Al cliente NO se le manda el traceback: puede filtrar
        # rutas de archivos y estructura interna de la aplicacion.
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"detail": "Error interno del servidor. Revisá el log."},
        )


# ---------------------------------------------------------------------------
# Errores de validacion (422) que contienen valores no serializables
# ---------------------------------------------------------------------------
# Cuando Pydantic rechaza un campo, el 422 incluye el valor que fallo en una
# clave "input", para que sepas QUE mandaste mal. Buenisimo... salvo cuando el
# valor rechazado es justamente infinito: al armar el JSON del mensaje de
# error, revienta por la misma razon por la que rechazamos el dato.
#
# O sea: el mensaje de error no se puede escribir porque contiene el dato que
# hace imposible escribirlo. Un 422 perfectamente correcto termina en 500.
#
# Solucion: convertir a texto los valores no finitos antes de serializar.
# El usuario igual ve "inf" y entiende que fue eso lo que mando mal.
@app.exception_handler(RequestValidationError)
async def errores_de_validacion(request: Request, exc: RequestValidationError) -> JSONResponse:
    errores = []
    for error in exc.errors():
        error = dict(error)
        entrada = error.get("input")
        if isinstance(entrada, float) and not math.isfinite(entrada):
            error["input"] = str(entrada)  # inf / -inf / nan
        errores.append(error)

    return JSONResponse(status_code=422, content=jsonable_encoder({"detail": errores}))


# ---------------------------------------------------------------------------
# CORS — ahora si, en serio
# ---------------------------------------------------------------------------
# Cuando el front y la API vivian en el mismo servidor, esto era decorativo.
# Ahora es lo unico que hace que el proyecto funcione.
#
# El navegador tiene una regla de seguridad: una pagina servida desde un origen
# NO puede hacerle pedidos a otro origen, salvo que el otro origen conteste
# explicitamente "si, este de aca tiene permiso". Un ORIGEN es la terna
# esquema + host + puerto:
#
#     http://localhost:3000   <- el front
#     http://localhost:8000   <- la API
#      ^        ^        ^
#      |        |        +-- distinto puerto => ORIGEN DISTINTO
#      +--------+----------- iguales
#
# OJO CON ESTO, que es la trampa que mas tiempo hace perder:
# http://localhost:3000 y http://127.0.0.1:3000 son ORIGENES DISTINTOS para el
# navegador, aunque sean literalmente la misma maquina. Por eso van los dos en
# la lista: para que funcione entres como entres.
#
# Y fijate lo importante: CORS lo aplica EL NAVEGADOR, no el servidor. Por eso
# curl y Postman nunca se quejan de CORS — no son navegadores, no tienen que
# proteger a nadie. Si tu fetch falla pero el curl anda, ya sabes donde mirar.
# De donde salen los origenes permitidos:
#
# En tu maquina no hace falta configurar nada: si la variable de entorno no
# existe, usamos los dos localhost de siempre y todo sigue andando igual.
#
# En un servidor de verdad, el dominio del front NO se puede saber de
# antemano — depende de que dominio compraste. Por eso viene de una variable
# de entorno, separando dominios con comas:
#
#   ORIGENES_PERMITIDOS=https://calculadora.midominio.com
#
# Esto es una regla general, no un capricho de este proyecto: TODO lo que
# cambia entre tu maquina y el servidor (dominios, claves, URLs de bases de
# datos) va en variables de entorno, nunca escrito en el codigo. Si lo hardcodeas,
# terminas con un archivo distinto en cada lugar y tarde o temprano subis a
# produccion el que apuntaba a tu localhost.
ORIGENES_LOCALES = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

_origenes_del_entorno = [
    origen.strip()
    for origen in os.getenv("ORIGENES_PERMITIDOS", "").split(",")
    if origen.strip()
]

ORIGENES_PERMITIDOS = _origenes_del_entorno or ORIGENES_LOCALES

# NO uses allow_origins=["*"] cuando podes nombrar los origenes. "*" significa
# "cualquier pagina de internet puede pegarle a mi API desde el navegador de
# mis usuarios". En una calculadora no pasa nada. En una API con datos de
# alguien, es un agujero.
#
# OJO CON EL ORDEN: en Starlette, el ULTIMO middleware agregado es el MAS
# EXTERNO. Por eso CORS va DESPUES de la red de seguridad — asi CORS envuelve
# a la red de seguridad y le agrega los headers hasta a las respuestas 500.
# Si invertis estas dos secciones, los 500 vuelven a salir sin CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGENES_PERMITIDOS,
    allow_credentials=False,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["Content-Type"],
)


# ---------------------------------------------------------------------------
# Contratos de datos (Pydantic)
# ---------------------------------------------------------------------------
# Esto es lo que hace que FastAPI sea FastAPI. No escribimos ni un if para
# validar: declaramos la FORMA que tienen que tener los datos y el framework
# rechaza solo todo lo que no encaje, con un 422 y un mensaje explicando que
# campo esta mal.

Operacion = Literal["suma", "resta", "multiplicacion", "division"]

# Tabla unica: cada operacion sabe su simbolo y como se calcula.
# Un solo lugar para agregar una operacion nueva -> un solo lugar donde
# equivocarse. Si manana querés potencia, agregas UNA linea aca.
# El tipo de cada lambda es Callable[[float, float], float]: "funcion que toma
# dos floats y devuelve un float". OJO: `callable` en minuscula es OTRA cosa —
# es la funcion built-in que pregunta si algo se puede llamar. Usarla como
# anotacion no rompe en runtime (Python no chequea tipos), pero mypy la rechaza
# y quien lea el codigo se confunde.
OPERACIONES: dict[str, tuple[str, Callable[[float, float], float]]] = {
    "suma": ("+", lambda a, b: a + b),
    "resta": ("-", lambda a, b: a - b),
    "multiplicacion": ("*", lambda a, b: a * b),
    "division": ("/", lambda a, b: a / b),
}


class OperacionRequest(BaseModel):
    """Lo que el front NOS MANDA."""

    a: float = Field(..., description="Primer operando (numero finito)")
    b: float = Field(..., description="Segundo operando (numero finito)")
    operacion: Operacion = Field(..., description="Que hacer con a y b")

    @field_validator("a", "b")
    @classmethod
    def debe_ser_finito(cls, valor: float) -> float:
        """
        Rechaza infinito y NaN en la ENTRADA.

        Hace falta explicitamente porque `float` en Pydantic los acepta:
          - el JSON 1e400 se parsea como infinito, sin queja
          - los strings "inf" y "nan" se coaccionan a float sin queja
            (mientras que "hola" si da un 422, lo cual es confuso)

        Si los dejaras pasar, la cuenta se hace igual y el problema aparece
        recien al serializar la respuesta — un 500 por un dato del cliente.
        Un dato de entrada invalido es 422, y se rechaza ACA, antes de calcular.
        """
        if not math.isfinite(valor):
            raise ValueError("debe ser un numero finito (ni infinito ni NaN)")
        return valor

    # Este ejemplo aparece en la documentacion automatica de /docs.
    model_config = {
        "json_schema_extra": {
            "example": {"a": 10, "b": 3, "operacion": "division"}
        }
    }


class OperacionResponse(BaseModel):
    """Lo que NOSOTROS LE DEVOLVEMOS al front."""

    a: float
    b: float
    operacion: str
    simbolo: str
    resultado: float
    expresion: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
# Todo lo de la API cuelga de /api/*. Aunque hoy este servidor no sirva otra
# cosa, el prefijo deja claro donde termina la API y evita choques si manana
# le agregas algo mas (metricas, un panel, lo que sea).

@app.post("/api/calcular", response_model=OperacionResponse, tags=["calculadora"])
def calcular(datos: OperacionRequest) -> OperacionResponse:
    """
    Recibe dos numeros y una operacion, devuelve el resultado.

    Cuando esta funcion arranca, `datos` YA esta validado: a y b son floats de
    verdad y operacion es una de las cuatro permitidas. Por eso el cuerpo puede
    ser tan corto — el trabajo sucio lo hizo Pydantic antes de llegar aca.
    """
    simbolo, calcular_fn = OPERACIONES[datos.operacion]

    # Regla de negocio 1: division por cero. Pydantic no puede validarla sola
    # porque depende de la COMBINACION de dos campos, no de uno solo.
    if datos.operacion == "division" and datos.b == 0:
        # 400 = "vos me mandaste algo que no puedo procesar".
        # No es un 500: el servidor esta perfecto, el pedido es el invalido.
        raise HTTPException(status_code=400, detail="No se puede dividir por cero.")

    resultado = calcular_fn(datos.a, datos.b)

    # Regla de negocio 2: el resultado tiene que entrar en un float.
    # Los dos operandos pueden ser finitos y perfectamente validos, y aun asi
    # su resultado desbordarse: 1e308 * 10 da infinito. Y aca esta el detalle
    # que sorprende a todo el mundo: INFINITO NO EXISTE EN JSON. El estandar no
    # lo contempla.
    #
    # Si esto llegara al serializador, revienta con
    #   ValueError: Out of range float values are not JSON compliant: inf
    # y la API contesta 500 — o sea, "yo me rompi" por un dato que mando el
    # cliente. Es mentira y confunde a quien debuggea. Es un 400.
    if not math.isfinite(resultado):
        raise HTTPException(
            status_code=400,
            detail=(
                "El resultado quedo fuera del rango que puede representar la "
                "computadora (mas o menos 1.8e308). Probá con numeros mas chicos."
            ),
        )

    return OperacionResponse(
        a=datos.a,
        b=datos.b,
        operacion=datos.operacion,
        simbolo=simbolo,
        resultado=resultado,
        expresion=f"{datos.a} {simbolo} {datos.b} = {resultado}",
    )


@app.get("/api/salud", tags=["infra"])
def salud() -> dict[str, str]:
    """Healthcheck. Sirve para saber si la API esta viva sin hacer una cuenta."""
    return {"estado": "ok"}


# Y aca se termina el backend.
#
# Fijate lo que NO hay en este archivo: ni una etiqueta HTML, ni una linea de
# CSS, ni el nombre de un boton. Este servidor no sabe que existe una
# calculadora con botones lindos. Sabe recibir dos numeros y una operacion.
#
# Esa ignorancia es la ventaja. Manana le podes poner adelante una app de
# celular, un script de Python o una planilla, y este archivo no cambia una
# coma. A eso se referia el pedido de "independizarlos".
