# directo-clips

Le dices a Claude «recorta este directo: <enlace>» y, mientras el directo sigue en marcha, te va dejando clips verticales (1080x1920) con subtítulos de los momentos en que el chat se vuelve loco.

Funciona con directos de Twitch y de YouTube. Es gratis y no necesita ninguna cuenta ni clave.

## Qué hace, en llano

1. Mira el chat del directo y cuenta cuántos mensajes hay cada 10 segundos.
2. Calcula lo que es «normal» en ese directo. Cuando una ventana se pasa mucho de lo normal, lo marca como pico.
3. Mientras tanto va guardando el vídeo en trozos cortos de 4 segundos en tu disco (solo guarda los últimos minutos).
4. En cada pico corta desde 20 segundos antes hasta 10 después, lo pasa a vertical, escribe lo que se dice con Whisper y lo pega como subtítulo grande.
5. Deja los clips en la carpeta `clips/` y un `clips.json` con la hora, los mensajes de esa ventana y el texto dicho.

## Qué hay en la carpeta

- `directo_clips.py`: el programa.
- `CLAUDE.md`: las instrucciones que lee Claude Code al abrir esta carpeta. Por eso basta con decirle «recorta este directo».
- `MENSAJE-PRIMER-CREADOR.md`: el mensaje para ofrecerle una prueba a un creador.
- `LEEME.md`: esto.

## Instalación

Se ha probado solo en un Mac con chip de Apple. En Windows o Linux puede funcionar, pero no está probado.

Lo más cómodo es que lo instale Claude: abre Claude Code dentro de esta carpeta y pídele que lea este archivo e instale lo que falte, paso a paso. A mano, en un Mac con [Homebrew](https://brew.sh), son cuatro cosas:

**1. Los tres programas:** `yt-dlp` (baja el directo), `ffmpeg` (corta y pasa a vertical) y `whisper-cli` (escribe lo que se dice; viene en el paquete `whisper-cpp`).

```
brew install yt-dlp ffmpeg whisper-cpp
```

**2. El modelo de Whisper,** el archivo `ggml-small.bin` (casi 500 MB), dentro de una carpeta `modelos/` en esta misma carpeta:

```
mkdir -p modelos
curl -L -o modelos/ggml-small.bin https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin
```

Si ya lo tienes en otro sitio, apunta a esa carpeta con la variable `WHISPER_MODELOS`.

**3. Un entorno propio de Python con Pillow** (dibuja los subtítulos), en `.venv/`:

```
python3 -m venv .venv
.venv/bin/pip install pillow
```

**4. Comprobar que arranca:**

```
.venv/bin/python directo_clips.py --help
```

Si falta algo, el programa lo dice al arrancar («Falta ffmpeg», «No encuentro el modelo...»).

## Cómo pedírselo a Claude

Abre Claude Code en esta carpeta y escribe, por ejemplo:

> Recorta este directo: https://www.twitch.tv/canal. Máximo 3 clips, vigila 30 minutos.

Comando equivalente a mano:

```
.venv/bin/python directo_clips.py "https://www.twitch.tv/canal" --max-clips 3 --minutos 30
```

Ajustes: `--k` (más bajo = más clips; por defecto 3), `--min-mensajes`, `--modelo large-v3` (mejor subtitulado, más lento; hay que descargar ese modelo igual que el `small`), `--encuadre centro` (recorte centrado en vez del directo entero sobre fondo desenfocado), `--idioma es`.

## Qué sale

- `clips/clip-01-HHMMSS.mp4`: vertical 1080x1920, unos 30 s, con audio y subtítulos.
- `clips/clips.json`: archivo, hora, mensajes en la ventana, lo normal del directo, texto dicho y segundos que tardó en salir.
- Un clip sale unos 30 a 45 segundos después del pico (10 de espera para cortar «hacia delante», unos 4 de trozo y el resto de montaje y transcripción).

## Publicar (opcional, apagado)

`--publicar` sube cada clip a Zernio, un servicio de publicación en redes. Necesita la variable `ZERNIO_API_KEY` con una clave tuya y `--cuentas instagram:ID,tiktok:ID`. Con `--ensayo` solo imprime lo que mandaría. `--borrador` lo deja como borrador en vez de publicarlo.

**Este paso NO está probado contra una cuenta real.** Está escrito con la documentación pública de Zernio (subida con `/media/presign`, luego `POST /posts`) y solo se ha probado el modo ensayo.

## Qué se ha probado de verdad (21 de noviembre de 2026)

En un Mac con chip de Apple, con yt-dlp 2026.08.19, ffmpeg 8.1, whisper.cpp 1.9.5 y Pillow 13:

- Twitch, canal kaicenat, directo grande con chat activo: 7 minutos de vigilancia, umbral bajo (`--k 1.0`), 2 clips. Comprobados con `ffprobe`: 1080x1920, vídeo H.264 y audio AAC, 30 s y 29,7 s. Miradas tres imágenes del primer clip y otras tres del segundo: se ve el directo entero sobre fondo desenfocado y los subtítulos se leen bien. Tardaron 33,7 y 31,4 s desde el pico.
- YouTube, directo 24/7 de Lofi Girl: 5 minutos, 1 clip de 30 s, 1080x1920 con audio. El chat de YouTube se lee sin clave. Su audio es solo música, así que no hay subtítulos (correcto, no hay nada que transcribir).
- Modo ensayo de la publicación: imprime las llamadas que haría.

## Qué NO se ha probado

- La publicación real en Zernio.
- Windows y Linux.
- Directos de varias horas (la prueba más larga fue de 7 minutos).
- Un pico de chat «de verdad» (explosión por algo grande): con el umbral bajo de la prueba, los picos eran subidas normales del chat. Con el umbral por defecto saldrán menos clips, probablemente buenos.
- Subtítulos en español en un directo de gamer: la prueba fue con audio en inglés. Whisper detecta el idioma solo.
- Directos de YouTube con mucha charla y chat grande.

## Límites honestos

- Solo funciona con el directo en marcha: no recorta vídeos ya subidos ni repeticiones. Si cierras el ordenador o Claude, deja de vigilar.
- Los anuncios de Twitch pueden colarse en el vídeo y en un clip.
- Los clips son del streamer. Para publicarlos tienes que tener su permiso; por eso el mensaje de `MENSAJE-PRIMER-CREADOR.md` ofrece una prueba y no publicar por tu cuenta.
- El encuadre es siempre el mismo (sin IA de visión): no sigue al jugador ni a la cámara.
- El momento exacto es aproximado (unos 1-2 s de margen) y el chat reacciona unos segundos tarde, por eso se cortan 20 s antes.
- Whisper falla con música alta o mucho ruido de juego, y puede inventar alguna frase; para clips publicables hay que revisar los subtítulos.
- La lectura del chat de YouTube usa la página pública del chat, sin clave: si YouTube la cambia, puede dejar de funcionar. Twitch usa el chat anónimo oficial.
