# directo-clips · instrucciones para Claude

Esta carpeta es una herramienta que recorta un directo de Twitch o YouTube EN MARCHA: vigila el chat, detecta los picos de mensajes y saca clips verticales 1080x1920 con subtítulos. Úsala cuando el usuario diga «recorta este directo», «saca clips de este stream» o pegue el enlace de un directo en marcha. No sirve para vídeos ya subidos.

Explícale cada paso en lenguaje llano: quien la usa no tiene por qué saber programar.

## Si te pide instalarla

Sigue la sección «Instalación» de `LEEME.md`, paso a paso. Comprueba primero qué está ya instalado, instala solo lo que falte y dile qué has instalado antes de seguir. No actives ninguna opción de publicar.

## Si te pide recortar un directo

1. Pide, si no los ha dado: el enlace del directo, cuántos clips como máximo (por defecto 3) y cuántos minutos vigilar (por defecto 30). No preguntes nada más.
2. Comprueba que el programa arranca: `.venv/bin/python directo_clips.py --help`. Si falta algo, dilo y ofrece instalarlo con el `LEEME.md`.
3. Lanza la herramienta en segundo plano desde esta carpeta (puede tardar la media hora entera) y ve leyendo el registro:

```
mkdir -p pruebas
.venv/bin/python directo_clips.py "<ENLACE>" --max-clips 3 --minutos 30 > pruebas/run.log 2>&1 &
```

4. Cada línea `ventana:` del registro es el recuento de mensajes de 10 s. `<== PICO` marca un clip; unos 35 s después aparece `clip N LISTO`. Avísale cada vez que salga uno.
5. Al terminar, enséñale la lista de `clips/clips.json` (archivo, hora, mensajes, texto dicho) y la ruta de la carpeta `clips/`.

## Ajustes útiles

- Salen pocos clips («hazlo más sensible»): `--k 1.5 --min-mensajes 5`.
- Salen demasiados («solo los picos grandes»): `--k 4`.
- El idioma se detecta solo; se fuerza con `--idioma es`.
- Mejor transcripción, más lenta: `--modelo large-v3` (hay que descargar ese modelo a `modelos/` igual que el `small`).
- Recorte centrado en vez de directo entero con fondo desenfocado: `--encuadre centro`.

## Publicar (opcional, apagado)

Nunca lo actives sin que el usuario lo pida. Primero `--publicar --ensayo --cuentas instagram:ID` para ver lo que mandaría; para publicar de verdad hace falta la variable `ZERNIO_API_KEY`. Ese paso no está probado contra una cuenta real: díselo.

## Avisos que debes dar

Los clips son del streamer: antes de publicar uno, tiene que estar de acuerdo. Los anuncios de Twitch pueden colarse en el vídeo. Si el ordenador se duerme, la herramienta deja de vigilar.
