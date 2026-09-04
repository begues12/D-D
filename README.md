# D&D Engine

Primera base de un motor de D&D independiente de la IA. Las reglas modifican el estado del mundo y publican eventos; una futura IA DM podra interpretar intenciones y narrar resultados sin inventar tiradas.

## Jugar

```powershell
python -m pip install -e .
python -m dnd_engine     # o: dnd-play
```

Para probarlo con una interfaz sencilla de escritorio:

```powershell
python -m dnd_engine.gui # o: dnd-gui
```

No necesita IA ni dependencias adicionales: usa Tkinter, incluido normalmente
con Python en Windows.

Se abre en un **asistente de tres pasos**:

1. **La aventura** - seis fichas: las cuatro escritas a mano y dos huecos que
   rellena la IA cuando pulsas *Que las invente la IA*. Se elige pulsando la
   ficha, y solo se construye el mundo de la elegida.
2. **El heroe** - los arquetipos, cada uno con sus puntos de golpe, su CA y lo
   que trae puesto, para compararlos de un vistazo.
3. **El nombre** - y el resumen de lo que vais a jugar antes de entrar.

Despues viene la sala de juego: el mapa con los tokens, el panel del personaje,
los botones de accion y el historial en pergamino, sobre la misma consola de
siempre.

Ahi tambien se introduce la clave de Anthropic. Si se marca "recordar", se
cifra con DPAPI y se guarda en las credenciales del usuario de Windows, fuera
de la partida JSON: no acaba en el repositorio ni en el historial.

### La cronica ilustrada

A la derecha de la sala de juego se va llenando un cuaderno: **una lamina por
escena**, con su emblema, su titulo y su pie. Aparece al abrir la aventura y cada
vez que se pisa una ubicacion nueva o se cierra una mision -no en cada turno, que
seria ruido y factura-.

De donde sale la lamina depende de lo que haya:

1. **Con una IA que dibuje**, la imagen que devuelva. Ninguna de las que hay
   ahora mismo lo hace; el hueco esta abierto en `providers.py`
   (`supports_images` / `generate_image`) y el dia que se anada una, la columna
   se llena de imagenes sin tocar nada mas.
2. **Con una IA de texto**, una llamada corta por escena: titulo, pie y un
   emblema de una lista cerrada, y la columna dibuja la lamina iluminada.
3. **Sin IA**, lo que ya sabe el motor: donde estas, que hay y quien esta. La
   columna nunca se queda vacia.

### Como esta hecho el aspecto

- **Colores, tipografias y medidas** viven en `theme.py`: se tocan `PALETTE`,
  `FONTS` o `SPACE` y cambia toda la aplicacion. No hay ni un color escrito a
  mano en el resto de la interfaz.
- **Las tipografias** (Cinzel para los rotulos, IM Fell English para el
  pergamino, MedievalSharp para los pies) viajan en `assets/fonts` con su
  licencia OFL y se cargan **solo para este proceso** con `AddFontResourceEx`: no
  se instalan en el sistema, no piden permisos y desaparecen al cerrar. Si no se
  pueden cargar, cada una cae en algo que existe en cualquier Windows.
- **Las texturas** -pergamino, cuero, madera- se dibujan pixel a pixel en
  `assets.py` y se codifican como PNG con `zlib`. Ni Pillow, ni imagenes
  descargadas, ni licencias que revisar; y como la semilla es fija, salen
  siempre iguales.
- **Los marcos** (`panels.py`) son un `Canvas` que pinta textura, filo dorado y
  florones en las esquinas, con un hueco dentro donde el resto del codigo mete
  sus widgets como siempre. Los emblemas de la cronica son cuatro trazos de
  `Canvas`: no hay iconos que descargar ni que licenciar.

Anadir un paso al asistente es anadirlo a `STEPS` y escribir su metodo: la
navegacion, la barra de progreso y el boton final ya funcionan.

Arranca con un menu hablado que pregunta cuantos sois, configura a cada uno y
propone aventuras -inventadas por la IA o del catalogo escrito a mano-; despues abre la consola de juego, donde `ayuda`
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
- `dice.py`: notacion `XdY+Z`, tiradas y su desglose.
- `rules.py`: ventaja/desventaja, ataques, salvaciones, salvaciones contra muerte, curacion y hechizos con condiciones temporales.
- `map.py`: cuadriculas, puertas, distancias y busqueda de camino.
- `actions.py`: catalogo de intenciones estructuradas y su ejecucion.
- `tactics.py`: turno automatico deterministico para los personajes no jugadores.
- `console.py`: CLI interactiva.
- `campaign.py`: catalogos, escenarios como planos y constructor de partidas.
- `menu.py`: menu hablado de preparacion.
- `forge.py`: la fragua, que le pide aventuras nuevas al modelo y las revisa.
- `gui.py`, `wizard.py`: la interfaz de escritorio y su asistente de preparacion.
- `theme.py`, `assets.py`, `panels.py`: colores y medidas, fuentes y texturas, y
  los marcos con filo dorado que usan las dos pantallas.
- `illustrator.py`, `chronicle.py`: las laminas de cada escena y la columna donde
  se apilan.
- `memory.py`: memoria de campana, suscrita al bus.
- `ai_dm.py`: DM basado en IA que interpreta y narra, sin decidir reglas.
- `providers.py`: que casa de IA hay detras, y lo unico que sabe de su SDK.
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

## Sistema de dados

Todo lo que se tira pasa por `Dice`, una expresion inmutable que se escribe como
se habla en la mesa: `2d6+3`, `d20`, `1d10-2` o `5` para una cantidad fija. El
arma, el hechizo y la pocion guardan su expresion, no un numero de caras suelto,
asi que un mandoble es `2d6+3` y una bola de fuego puede ser `8d6`.

```python
from dnd_engine import Dice, roll_dice

Dice.parse("2d6+3").average      # 10.0
Dice.parse("1d8+3").doubled()    # 2d8+3, el critico
roll_dice("2d6+3").detail        # '2d6+3 [5,2]+3 = 10'
```

Una tirada devuelve un `DiceRoll` con **los dados individuales a la vista**, no
solo el total. Ese desglose viaja en el resultado (`AttackResult.damage_roll`),
en el evento publicado (`damage_roll`) y en el resumen que lee quien juega, de
modo que la consola, la interfaz y el DM cuentan la tirada que de verdad ocurrio:

```
Aldric acierta a Goblin y le hace 10 de dano con Mandoble.
[d20=15 total=23 | dano 2d6+3 [5,2]+3 = 10] HP de Goblin: 4.
```

`tirar 2d6+3` en la consola hace una tirada suelta con el mismo lanzador que usa
el motor, asi que en los tests tambien es determinista.

Un critico duplica **los dados del arma, no el bonus**: `1d8+3` se convierte en
`2d8+3`. El lanzador sigue siendo inyectable y se comprueba tirada a tirada, asi
que un lanzador que devuelva algo fuera del dado falla en vez de colarse.

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
- Los consumibles (`Consumable`) curan (`healing`, en notacion de dados) o
  quitan un estado. `usar` los aplica
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

## Con que IA

**Con una clave, el juego se juega entero con IA**: el DM interpreta lo que
escribes y narra, y las aventuras se las inventa. Sin clave no se rompe nada,
pero se queda en los comandos de siempre y en los cuatro escenarios escritos.

Hoy la casa es Anthropic. Manana puede ser otra, y por eso el motor **no habla
con ningun SDK**: habla con un `Provider` (`providers.py`), que es el unico que
sabe de credenciales, modelos, formato de peticion y errores de una casa
concreta. Todo lo demas trabaja con dos cosas neutras: una peticion con
`system`, `messages` y `tools`, y una `Reply` con bloques de texto y de uso de
herramienta.

```powershell
python -m pip install -e ".[ai]"
$env:ANTHROPIC_API_KEY = "sk-ant-..."
python -m dnd_engine
```

En la interfaz grafica la clave se escribe en el primer paso, con un desplegable
para elegir la IA. Cada casa guarda **su propia clave** cifrada con DPAPI, asi
que se pueden tener varias y cambiar sin volver a escribirlas. `DND_AI_PROVIDER`
elige cual se usa por defecto.

Anadir otra IA es escribir una subclase de `Provider` y meterla en `PROVIDERS`:

```python
class OtraProvider(Provider):
    id, name = "otra", "Otra IA"
    env_var = "OTRA_API_KEY"
    default_model = "otra-grande"
    package = "otra_sdk"

    def create_client(self, retries=5): ...
    def create_message(self, client, **request) -> Reply: ...   # a formato neutro
    def assistant_echo(self, reply): ...                        # su turno, de vuelta
    def translate(self, error): ...                             # sus errores, en cristiano
```

Ni el DM, ni la fragua, ni el asistente se enteran. Hay un test que lo demuestra:
monta un proveedor de mentira, sin nada de Anthropic, y juega un turno completo.

## DM basado en IA

Traduce lenguaje natural a un `Intent` y narra el resultado real; no decide
reglas en ningun momento.

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
El menu pregunta cuantos sois y a cada jugador le pide nombre y arquetipo;
despues propone la historia -inventada o del catalogo-, el tono, la dificultad,
una premisa libre y si quieres el DM con IA. Antes de arrancar ensena el resumen y
deja cambiar cualquier apartado.

Todo sale por `SetupMenu.say()` y entra por `SetupMenu.ask()`, asi que ponerle
voz es sustituir esos dos metodos, no reescribir el flujo.

### Aventuras inventadas

Una vez sabe quienes sois, el menu pregunta si quereis aventuras nuevas. Si
dices que si,
la **fragua** (`forge.py`) le pide al modelo varias ideas a la vez, con el gancho
de cada una, y solo monta el mundo de la que elijas: proponer es barato y
construir no. Si ninguna convence, `Ninguna de estas` le pide otras tres -y se
le dice cuales ya ha propuesto, para que no las repita-; el catalogo escrito a
mano sigue estando a una respuesta de distancia.

```
Me las invento? [si]
De que quereis que vaya? Un lugar, un monstruo, una idea suelta.
> algo con agua

  1. El pozo de los nombres
     El pozo lleva once anos seco y aun asi alguien pide agua.
  2. La esclusa de los ahogados
     ...
  4. Ninguna de estas
  5. Las que ya tengo escritas
```

Lo que devuelve el modelo **no se juega sin revisar**. `validate_scenario` es la
aduana, y comprueba lo que rompe una partida:

- que los identificadores existan: puertas que dan a ubicaciones reales, llaves
  que son objetos de verdad, objetivos que apuntan a algo del escenario;
- que las casillas caigan dentro de la cuadricula (empezando en 0), no en un
  muro, y que dos criaturas no nazcan una encima de otra;
- que las tiradas se puedan leer (`1d8+2`) y los enemigos sean posibles;
- que la mision escuche eventos que el motor publica de verdad -otra cosa no se
  completaria nunca-;
- y que la aventura **se pueda terminar**: se recorre el mapa desde `start`
  abriendo solo lo que las llaves ya encontradas permiten, asi que una llave
  guardada detras de su propia puerta se rechaza.

Si algo no cuadra, el motivo exacto vuelve al modelo como resultado de su propia
herramienta y se le pide que corrija solo eso, hasta tres veces. Lo que sale de
ahi es el mismo `dict` que las entradas de `SCENARIOS`: viaja en
`CampaignSetup.blueprint`, se guarda con la partida y `build_campaign` no
distingue una aventura inventada de una escrita a mano.

```python
from dnd_engine import ScenarioForge

forge = ScenarioForge()
pitches = forge.propose(3, hint="algo con agua")   # una llamada, tres ideas
blueprint = forge.build(pitches[0])                # solo la elegida
```

La interfaz grafica hace lo mismo desde el primer paso del asistente: los
huecos marcados *IA* se llenan con estas propuestas.

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
que genera la fragua sin tocar el constructor.

```python
from dnd_engine.campaign import CampaignSetup, PlayerSetup, build_campaign

engine = build_campaign(CampaignSetup(
    players=[PlayerSetup("Aldric", "guerrero"), PlayerSetup("Nel", "mago")],
    scenario="cripta", tone="oscuro", difficulty="dificil",
))
```

La configuracion viaja en `world.state`, asi que se guarda y se carga con la
campana, y el tono y la premisa entran en el prompt de sistema del DM.
