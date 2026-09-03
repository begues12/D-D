# D&D Engine

Primera base de un motor de D&D independiente de la IA. Las reglas modifican el estado del mundo y publican eventos; una futura IA DM podra interpretar intenciones y narrar resultados sin inventar tiradas.

## Jugar

```powershell
python -m pip install -e .
python -m dnd_engine     # o: dnd-play
```

Arranca con un menu hablado que propone escenarios, pregunta cuantos jugadores
sois y configura a cada uno; despues abre la consola de juego, donde `ayuda`
lista los comandos. `dnd-demo` sigue ejecutando la demostracion corta y no
interactiva.

```
[Aldric 18/18 hp 30 pies] > abrir trapdoor
[Aldric 18/18 hp 30 pies] > ir cellar
[Aldric 18/18 hp 30 pies] > combate
[Aldric 18/18 hp 30 pies] > mover 4 3
[Aldric 18/18 hp 5 pies]  > atacar goblin-1
```

## Estructura

- `models.py`: personajes, NPCs, enemigos, objetos, armas, lugares, mundo, economia de turno y efectos de las condiciones.
- `rules.py`: dados con ventaja/desventaja, ataques, salvaciones, salvaciones contra muerte, curacion y hechizos con condiciones temporales.
- `map.py`: cuadriculas, puertas, distancias y busqueda de camino.
- `actions.py`: catalogo de intenciones estructuradas y su ejecucion.
- `tactics.py`: turno automatico deterministico para los personajes no jugadores.
- `console.py`: CLI interactiva.
- `campaign.py`: catalogos, escenarios como planos y constructor de partidas.
- `menu.py`: menu hablado de preparacion.
- `memory.py`: memoria de campana, suscrita al bus.
- `ai_dm.py`: DM basado en IA que interpreta y narra, sin decidir reglas.
- `events.py`: bus e historial de eventos del dominio.
- `world.py`: colocacion, movimiento validado, puertas y distancias.
- `quest.py`: misiones y objetivos que reaccionan a eventos.
- `persistence.py`: guardado y carga de campañas en JSON.
- `game.py`: fachada del motor para usarlo desde consola, tests o una futura IA.

## Principios

- El motor de reglas es determinista salvo por el lanzador de dados inyectable.
- Los cambios importantes generan eventos estructurados.
- La narracion, voz, audio y visuales quedan fuera del nucleo.
- Las misiones y la memoria podran suscribirse al bus sin acoplarse al combate.
- Quien juega (consola hoy, IA manana) solo produce `Intent`; nunca decide
  resultados.
- Un turno se inicia siempre por el mismo camino (`GameEngine.start_turn` o
  `GameEngine.next_turn`), que restaura la economia de turno, vence condiciones
  y publica un unico `TURN_STARTED`.

## Reglas de combate cubiertas

- Ventaja y desventaja: se piden por parametro o las imponen las condiciones, y
  se cancelan entre si.
- Economia de turno: accion, accion adicional, reaccion y movimiento restante.
- Condiciones con efecto real: incapacitado no actua y falla salvaciones de
  fuerza y destreza; cegado y envenenado atacan con desventaja; atacar a un
  objetivo cegado, aturdido, paralizado o inconsciente da ventaja.
- A 0 HP las criaturas mueren y los personajes jugadores caen inconscientes,
  tiran salvacion contra muerte al empezar su turno y pueden estabilizarse,
  revivir con un 20 natural o curarse.

## Mapa y movimiento

Cada ubicacion puede tener una `Grid` con las casillas intransitables. Una
casilla son 5 pies y la diagonal cuesta lo mismo que la ortogonal, asi que la
distancia es la de Chebyshev. Una ubicacion sin cuadricula es "teatro de la
mente": no hay posiciones y el motor no valida movimiento ni alcance dentro de
ella.

- Los objetos pueden estar en el suelo de una ubicacion, en una casilla
  concreta. `coger` exige estar al lado, igual que las puertas.
- Los consumibles (`Consumable`) curan o quitan un estado. `usar` los aplica
  sobre uno mismo o sobre alguien contiguo, y cuesta la accion. Se rechaza usar
  uno que no haria nada -curar a quien esta intacto, un antidoto sin veneno-
  para no gastarlo por una mala lectura.
- **La economia de turno solo se aplica dentro de un encuentro.** Fuera de
  combate no hay turnos, asi que no hay accion ni interaccion que gastar.
- `move` busca el camino mas corto esquivando muros y ocupantes, cobra su coste
  real del movimiento restante del turno y publica `CHARACTER_MOVED`. Si no hay
  ruta o no queda movimiento, falla en vez de teletransportar.
- Las ubicaciones se conectan con `Door`, que puede estar cerrada con llave y
  ocupar una casilla concreta a cada lado. `enter_location` exige una puerta
  abierta; `use_door` exige ademas estar junto a ella.
- El alcance de armas (`Weapon.reach`) y hechizos (`Spell.range_feet`) se
  comprueba en `GameEngine` cuando ambos estan en la misma cuadricula.

```python
world.add_location(Location("cellar", "Bodega", grid=Grid(6, 4, {(2, 1), (2, 2)})))
world.connect("tavern", "cellar", "trapdoor", cell_b=(0, 0), locked=True, key_id="cellar-key")
```

## Guardar una campana

```python
from dnd_engine.persistence import load_game, save_game

save_game(engine, "campaign.json")
engine = load_game("campaign.json")
```

## Intenciones

`actions.py` define el catalogo de acciones validas con sus parametros. La
consola construye un `Intent` parseando texto y el DM basado en IA construira el
mismo `Intent` a partir de lenguaje natural: ninguno de los dos toca las reglas.

```python
from dnd_engine.actions import Intent, action_schema, execute

execute(engine, Intent("attack", {"target": "goblin-1"}, actor_id="hero-1"))
action_schema()   # el catalogo serializable, para dárselo a un modelo
```

Los parametros se validan antes de tocar el motor: accion desconocida, parametro
que sobra, parametro que falta o de tipo incorrecto salen como `ValueError` con
un mensaje concreto.

## DM basado en IA

Opcional. Traduce lenguaje natural a un `Intent` y narra el resultado real; no
decide reglas en ningun momento.

```powershell
python -m pip install -e ".[ai]"
$env:ANTHROPIC_API_KEY = "sk-ant-..."
python -m dnd_engine
```

En la consola, `dm <texto>` manda una frase al DM, y `narrador` hace que todo lo
que no sea un comando conocido vaya al DM.

```
[Aldric 18/18 hp 30 pies] > dm me acerco al goblin y le meto un tajo
```

El ciclo son dos llamadas al modelo con el motor en medio:

1. **Interpretar** - el catalogo de `actions.py` viaja como herramientas de la
   API con `strict: true`, y `tool_choice` forzado garantiza que la respuesta sean
   siempre acciones estructuradas. Puede devolver **una secuencia** (hasta tres),
   porque los jugadores hablan asi: "me acerco a la rana y le clavo la espada"
   son un `move` y un `attack`, y la economia de turno permite las dos. Existe
   una herramienta `no_action` para lo que no es una accion del juego.
2. **El motor ejecuta** en orden, y para en el primer rechazo. Lo anterior ya ha
   ocurrido de verdad. El rechazo no es un fallo: su motivo exacto se le pasa al
   narrador.
3. **Narrar** - el modelo recibe los resultados reales y los eventos publicados,
   con instrucciones de no inventar tiradas, dano ni consecuencias.

Un turno nunca se pierde por un fallo de la API. Si falla la **interpretacion**,
no se ha tocado el mundo y la consola avisa de que se puede repetir la frase. Si
falla la **narracion**, el turno ya se ejecuto, asi que se cuenta en seco con los
resumenes del motor. Los errores de sobrecarga (429, 529, 5xx) se reintentan
cinco veces antes de rendirse.

El cliente se inyecta en el constructor (`DungeonMaster(client)`), asi que los
tests del DM no tocan la red.

## Memoria de campana

`CampaignMemory` se suscribe al bus y guarda dos cosas distintas a proposito:

- **Hechos** (`facts`), indexados por clave y sin caducidad: quien murio, que
  misiones se cerraron, que lugares se visitaron, que puertas se abrieron. Es lo
  que sobrevive a cualquier recorte.
- **Cronica** (`entries`), acotada: los sucesos recientes, lo que dijo el jugador
  y lo que narro el DM. Cuando se llena, lo viejo se cae y se cuenta cuanto.

Los eventos ruidosos -ataques, movimientos, turnos, tiradas sueltas- no entran:
llenarian la cronica en dos combates. `recall()` compone el bloque que reciben
las dos llamadas del DM, y es lo que le da continuidad entre turnos. En la
consola, `memoria` lo muestra.

El historial del bus (`EventBus.history`) es ahora una cola de depuracion con
tope; el registro duradero de la campana es la memoria.

## Preparar una campana

`python -m dnd_engine` no empieza en una partida: empieza en una conversacion.
El menu propone las historias disponibles con su gancho, pregunta cuantos sois,
y a cada jugador le pide nombre y arquetipo. Despues elige tono, dificultad, una
premisa libre y si quieres el DM con IA. Antes de arrancar ensena el resumen y
deja cambiar cualquier apartado.

Todo sale por `SetupMenu.say()` y entra por `SetupMenu.ask()`, asi que ponerle
voz es sustituir esos dos metodos, no reescribir el flujo.

### Catalogos

- **Escenarios**: el sotano del Dragon Rojo, la cripta del Rey Sin Nombre, la
  torre del alquimista y el vado de los ahogados. Cada uno son tres ubicaciones
  con sus cuadriculas, puertas, enemigos, PNJs, botin y mision. Las llaves estan
  repartidas por el mundo, no en el inventario inicial: hay que encontrarlas, y
  cada escenario esconde ademas algun consumible.
- **Arquetipos**: guerrero, explorador, mago y picaro, con sus caracteristicas,
  equipo, pocion de curacion y hechizos.
- **Tonos**: heroico, oscuro, misterio, humor y crudo. Solo afectan a como narra
  el DM, nunca a las reglas.
- **Dificultad**: escala los puntos de golpe y la CA de los enemigos. El tamano
  del grupo tambien los engrosa.

Los escenarios son **planos** (`dict` con locations, doors, enemies y quest), no
codigo. Anadir uno es anadir una entrada a `SCENARIOS`, y ese mismo formato es el
que podra generar un modelo mas adelante sin tocar el constructor.

```python
from dnd_engine.campaign import CampaignSetup, PlayerSetup, build_campaign

engine = build_campaign(CampaignSetup(
    players=[PlayerSetup("Aldric", "guerrero"), PlayerSetup("Nel", "mago")],
    scenario="cripta", tone="oscuro", difficulty="dificil",
))
```

La configuracion viaja en `world.state`, asi que se guarda y se carga con la
campana, y el tono y la premisa entran en el prompt de sistema del DM.
