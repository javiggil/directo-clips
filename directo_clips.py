#!/usr/bin/env python3
"""directo-clips: vigila el chat de un directo en marcha, y cuando se dispara
corta un clip vertical 1080x1920 con subtitulos quemados (Whisper).

Uso minimo:
    .venv/bin/python directo_clips.py https://www.twitch.tv/CANAL --max-clips 3 --minutos 30

Solo libreria estandar + Pillow (para dibujar los subtitulos) + yt-dlp, ffmpeg y whisper-cli del sistema.
"""
import argparse, collections, json, math, os, re, shutil, socket, statistics
import subprocess, sys, tempfile, threading, time, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
FUENTES = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf",
           "/System/Library/Fonts/Supplemental/Arial Black.ttf",
           "/System/Library/Fonts/HelveticaNeue.ttc",
           "/Library/Fonts/Arial Bold.ttf",
           "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
           "C:/Windows/Fonts/arialbd.ttf"]
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SEG = 4  # segundos por trozo del bufer


def ruta_modelo(nombre):
    """Donde esta ggml-<nombre>.bin: la carpeta modelos/ de la herramienta, la variable WHISPER_MODELOS
    o las carpetas de cache habituales. None si no aparece."""
    carpetas = [AQUI / "modelos"]
    if os.environ.get("WHISPER_MODELOS"):
        carpetas.append(Path(os.environ["WHISPER_MODELOS"]).expanduser())
    carpetas += [Path.home() / ".cache/whisper.cpp", Path.home() / ".cache/hyperframes/whisper/models"]
    for c in carpetas:
        if (c / f"ggml-{nombre}.bin").exists():
            return c / f"ggml-{nombre}.bin"
    return None


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


# --------------------------------------------------------------- chat
class Contador:
    """Cuenta mensajes con marca de tiempo (hilo seguro)."""
    def __init__(self):
        self.t = collections.deque()
        self.lock = threading.Lock()
        self.total = 0
        self.ultimo = None

    def add(self, ts=None):
        with self.lock:
            self.t.append(ts or time.time())
            self.total += 1
            self.ultimo = time.time()

    def entre(self, a, b):
        with self.lock:
            while self.t and self.t[0] < a - 600:
                self.t.popleft()
            return sum(1 for x in self.t if a <= x < b)


def canal_twitch(url):
    m = re.search(r"twitch\.tv/([A-Za-z0-9_]+)", url)
    return m.group(1).lower() if m else None


def chat_twitch(canal, cont, parar):
    """IRC anonimo de Twitch, sin cuenta ni clave."""
    while not parar.is_set():
        try:
            s = socket.create_connection(("irc.chat.twitch.tv", 6667), timeout=30)
            s.sendall(b"NICK justinfan12345\r\nJOIN #" + canal.encode() + b"\r\n")
            s.settimeout(30)
            buf = b""
            log(f"chat: conectado a #{canal}")
            while not parar.is_set():
                try:
                    d = s.recv(4096)
                except socket.timeout:
                    continue
                if not d:
                    break
                buf += d
                while b"\r\n" in buf:
                    linea, buf = buf.split(b"\r\n", 1)
                    if linea.startswith(b"PING"):
                        s.sendall(b"PONG :tmi.twitch.tv\r\n")
                    elif b" PRIVMSG " in linea:
                        cont.add()
            s.close()
        except Exception as e:
            log("chat: error", e)
        time.sleep(3)


def _http(url, datos=None, cab=None):
    r = urllib.request.Request(url, datos, {"User-Agent": UA, "Accept-Language": "es", **(cab or {})})
    return urllib.request.urlopen(r, timeout=20).read().decode("utf-8", "replace")


def chat_youtube(video_id, cont, parar):
    """Chat de YouTube leyendo la pagina publica del chat (sin clave). Menos estable que Twitch."""
    try:
        html = _http(f"https://www.youtube.com/live_chat?is_popout=1&v={video_id}")
        key = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', html).group(1)
        ver = re.search(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"', html).group(1)
        cont_tok = re.search(r'"continuation":"([^"]+)"', html).group(1)
    except Exception as e:
        log("chat youtube: no he podido abrir el chat (¿directo sin chat?)", e)
        return
    log("chat: conectado al chat de YouTube", video_id)
    vistos = collections.deque(maxlen=2000)
    while not parar.is_set():
        try:
            cuerpo = json.dumps({"context": {"client": {"clientName": "WEB", "clientVersion": ver}},
                                 "continuation": cont_tok}).encode()
            d = json.loads(_http(f"https://www.youtube.com/youtubei/v1/live_chat/get_live_chat?key={key}",
                                 cuerpo, {"Content-Type": "application/json"}))
            c = d["continuationContents"]["liveChatContinuation"]
            for a in c.get("actions", []):
                it = a.get("addChatItemAction", {}).get("item", {})
                for k, v in it.items():
                    if k.startswith("live") and k.endswith("Renderer") and v.get("id") not in vistos:
                        if k in ("liveChatTextMessageRenderer", "liveChatPaidMessageRenderer"):
                            vistos.append(v.get("id"))
                            cont.add()
            sig = c["continuations"][0]
            dd = sig.get("invalidationContinuationData") or sig.get("timedContinuationData") or {}
            cont_tok = dd["continuation"]
            time.sleep(max(0.5, min(dd.get("timeoutMs", 2000), 5000) / 1000))
        except Exception as e:
            log("chat youtube: error", e)
            time.sleep(4)


# --------------------------------------------------------------- video
def resolver(url, calidad):
    r = subprocess.run(["yt-dlp", "-g", "--no-warnings", "-f", calidad, url],
                       capture_output=True, text=True, timeout=90)
    lineas = [l for l in r.stdout.splitlines() if l.startswith("http")]
    if not lineas:
        sys.exit("No he podido abrir el directo (¿esta en marcha?): " + r.stderr.strip()[-300:])
    return lineas


def lanzar_buffer(urls, buf):
    ent = []
    for u in urls:
        ent += ["-i", u]
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", *ent]
    if len(urls) > 1:
        cmd += ["-map", "0:v:0", "-map", "1:a:0"]
    cmd += ["-c", "copy", "-f", "segment", "-segment_time", str(SEG), "-strftime", "1",
            "-segment_format", "mpegts", "-reset_timestamps", "1", str(buf / "seg_%s.ts")]
    return subprocess.Popen(cmd, stderr=subprocess.PIPE)


def segmentos(buf):
    out = []
    for p in buf.glob("seg_*.ts"):
        try:
            out.append((int(p.stem[4:]), p))
        except ValueError:
            pass
    return sorted(out)


def podar(buf, conservar):
    corte = time.time() - conservar
    for e, p in segmentos(buf)[:-2]:
        if e < corte:
            p.unlink(missing_ok=True)


# --------------------------------------------------------------- subtitulos
def buscar_fuente():
    for f in FUENTES:
        if os.path.exists(f):
            return f
    sys.exit("No encuentro una fuente en negrita para los subtitulos.")


def transcribir(wav, modelo, idioma, tmp):
    base = tmp / "voz"
    cmd = ["whisper-cli", "-m", str(ruta_modelo(modelo)), "-f", str(wav), "-l", idioma,
           "-ml", "26", "-sow", "-oj", "-of", str(base), "-np"]
    subprocess.run(cmd, capture_output=True, timeout=600)
    try:
        d = json.load(open(str(base) + ".json", encoding="utf-8"))
    except Exception:
        return []
    cues, previo = [], ""
    for s in d.get("transcription", []):
        txt = s["text"].strip()
        if not txt or re.fullmatch(r"[\[\(].*[\]\)]|[♪\s\.\-]*", txt):
            continue
        if txt.lower() == previo:  # alucinacion tipica: la misma frase repetida
            continue
        previo = txt.lower()
        cues.append((s["offsets"]["from"] / 1000, max(s["offsets"]["to"] / 1000, s["offsets"]["from"] / 1000 + 0.6), txt))
    # une trozos muy cortos para que no parpadeen
    unidos = []
    for a, b, t in cues:
        if unidos and len(unidos[-1][2]) + len(t) < 30 and a - unidos[-1][1] < 0.4:
            unidos[-1] = (unidos[-1][0], b, unidos[-1][2] + " " + t)
        else:
            unidos.append((a, b, t))
    return unidos


def dibujar_cue(texto, ruta, fuente):
    from PIL import Image, ImageDraw, ImageFont
    f = ImageFont.truetype(fuente, 84)
    d0 = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    palabras, lineas, act = texto.split(), [], ""
    for p in palabras:
        prueba = (act + " " + p).strip()
        if d0.textlength(prueba, font=f) > 960 and act:
            lineas.append(act)
            act = p
        else:
            act = prueba
    lineas.append(act)
    alto = 100 * len(lineas) + 20
    im = Image.new("RGBA", (1080, alto), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i, l in enumerate(lineas):
        w = d.textlength(l, font=f)
        d.text(((1080 - w) / 2, 10 + i * 100), l, font=f, fill="white",
               stroke_width=7, stroke_fill="black")
    im.save(ruta)
    return alto


# --------------------------------------------------------------- clip
def ffprobe_dur(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def hacer_clip(buf, t0, t1, destino, args, fuente):
    """Une los trozos que cubren [t0, t1] y genera el vertical con subtitulos."""
    segs = [(e, p) for e, p in segmentos(buf) if e + SEG + 2 >= t0 and e <= t1]
    if not segs:
        raise RuntimeError("el bufer ya no tiene esa franja")
    with tempfile.TemporaryDirectory(dir=buf.parent) as td:
        tmp = Path(td)
        lista = tmp / "lista.txt"
        lista.write_text("".join(f"file '{p}'\n" for _, p in segs))
        corte = tmp / "corte.mp4"
        off = max(0.0, t0 - segs[0][0])
        dur = t1 - t0
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(lista), "-ss", f"{off:.2f}", "-t", f"{dur:.2f}",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "160k",
                        "-r", "30", str(corte)], check=True)
        wav = tmp / "a.wav"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(corte), "-vn",
                        "-ac", "1", "-ar", "16000", str(wav)], check=True)
        cues = transcribir(wav, args.modelo, args.idioma, tmp)
        entradas, filtros, ultimo = ["-i", str(corte)], [], "v0"
        if args.encuadre == "centro":
            base = "[0:v]scale=-2:1920,crop=1080:1920,setsar=1[v0]"
            ysub = 1380
        else:  # pad: directo entero centrado sobre su propio fondo desenfocado
            base = ("[0:v]split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,"
                    "crop=1080:1920,gblur=sigma=40,eq=brightness=-0.15[bg];[b]scale=1080:-2[fg];"
                    "[bg][fg]overlay=(W-w)/2:(H-h)/2-140,setsar=1[v0]")
            ysub = 1250
        filtros.append(base)
        for i, (a, b, t) in enumerate(cues):
            png = tmp / f"c{i}.png"
            dibujar_cue(t, png, fuente)
            entradas += ["-i", str(png)]
            sig = f"v{i+1}"
            filtros.append(f"[{ultimo}][{i+1}:v]overlay=0:{ysub}:enable='between(t,{a:.2f},{b:.2f})'[{sig}]")
            ultimo = sig
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *entradas,
                        "-filter_complex", ";".join(filtros), "-map", f"[{ultimo}]", "-map", "0:a:0",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(destino)], check=True)
    return " ".join(t for _, _, t in cues)


# --------------------------------------------------------------- publicar (Zernio)
ZERNIO = "https://zernio.com/api/v1"


def zernio(metodo, ruta, clave, cuerpo=None):
    r = urllib.request.Request(ZERNIO + ruta, json.dumps(cuerpo).encode() if cuerpo is not None else None,
                               {"Authorization": f"Bearer {clave}", "Content-Type": "application/json"}, method=metodo)
    try:
        return json.loads(urllib.request.urlopen(r, timeout=60).read() or b"{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Zernio {e.code}: {e.read().decode()[:300]}")


def publicar_clip(clip, texto, args):
    """Sube el clip a Zernio. NO PROBADO contra una cuenta real: hecho a partir de la documentacion publica."""
    plataformas = []
    for par in args.cuentas.split(","):
        if ":" in par:
            p, i = par.split(":", 1)
            plataformas.append({"platform": p.strip(), "accountId": i.strip()})
    cuerpo = {"content": (args.pie or "Momento del directo").strip(),
              "mediaItems": [{"type": "video", "url": "<URL-PUBLICA-TRAS-SUBIR>"}],
              "platforms": plataformas}
    if args.borrador:
        cuerpo["isDraft"] = True
    else:
        cuerpo["publishNow"] = True
    if args.ensayo:
        print(f"[ENSAYO] POST {ZERNIO}/media/presign  {{'filename': '{clip.name}', 'contentType': 'video/mp4', 'size': {clip.stat().st_size}}}")
        print(f"[ENSAYO] PUT <uploadUrl> con {clip.name} (Content-Type: video/mp4)")
        print(f"[ENSAYO] POST {ZERNIO}/posts  {json.dumps(cuerpo, ensure_ascii=False)}")
        return "ensayo"
    clave = os.environ.get("ZERNIO_API_KEY")
    if not clave:
        raise RuntimeError("falta la variable de entorno ZERNIO_API_KEY")
    pre = zernio("POST", "/media/presign", clave, {"filename": clip.name, "contentType": "video/mp4",
                                                   "size": clip.stat().st_size})
    put = urllib.request.Request(pre["uploadUrl"], clip.read_bytes(), {"Content-Type": "video/mp4"}, method="PUT")
    urllib.request.urlopen(put, timeout=300).read()
    cuerpo["mediaItems"][0]["url"] = pre["publicUrl"]
    res = zernio("POST", "/posts", clave, cuerpo)
    return res.get("post", {}).get("_id", "enviado")


# --------------------------------------------------------------- principal
def main():
    ap = argparse.ArgumentParser(description="Clips verticales con subtitulos de los picos de chat de un directo en marcha.")
    ap.add_argument("url", help="enlace del directo (Twitch o YouTube)")
    ap.add_argument("--max-clips", type=int, default=3)
    ap.add_argument("--minutos", type=float, default=30, help="cuanto rato vigilar")
    ap.add_argument("--ventana", type=float, default=10, help="segundos por ventana de chat")
    ap.add_argument("--k", type=float, default=3.0, help="pico = media + k * desviacion (mas bajo, mas clips)")
    ap.add_argument("--min-mensajes", type=int, default=8, help="minimo de mensajes en la ventana para contar como pico")
    ap.add_argument("--calentamiento", type=int, default=6, help="ventanas a observar antes de poder detectar picos")
    ap.add_argument("--historia", type=int, default=30, help="ventanas usadas para calcular lo normal")
    ap.add_argument("--antes", type=float, default=20)
    ap.add_argument("--despues", type=float, default=10)
    ap.add_argument("--enfriamiento", type=float, default=45, help="segundos minimos entre picos")
    ap.add_argument("--modelo", default="small", help="modelo de whisper (small va rapido; large-v3 es el mejor)")
    ap.add_argument("--idioma", default="auto", help="idioma del audio, o auto")
    ap.add_argument("--encuadre", choices=["pad", "centro"], default="pad",
                    help="pad: directo entero con fondo desenfocado; centro: recorte centrado")
    ap.add_argument("--calidad", default=None, help="formato de yt-dlp (por defecto, 720p)")
    ap.add_argument("--salida", default=str(AQUI / "clips"))
    ap.add_argument("--trabajo", default=str(AQUI / "pruebas" / "buf"), help="donde va el bufer rodante")
    ap.add_argument("--publicar", action="store_true", help="OPCIONAL: sube cada clip a Zernio (apagado por defecto)")
    ap.add_argument("--ensayo", action="store_true", help="con --publicar: solo imprime lo que mandaria")
    ap.add_argument("--borrador", action="store_true", help="con --publicar: guarda como borrador en vez de publicar")
    ap.add_argument("--cuentas", default=os.environ.get("ZERNIO_CUENTAS", ""),
                    help="plataforma:idDeCuenta separadas por comas, p. ej. instagram:abc123,tiktok:def456")
    ap.add_argument("--pie", default="", help="texto que acompana al clip al publicar")
    args = ap.parse_args()

    for b in ("yt-dlp", "ffmpeg", "ffprobe", "whisper-cli"):
        if not shutil.which(b):
            sys.exit(f"Falta {b}")
    if not ruta_modelo(args.modelo):
        sys.exit(f"No encuentro el modelo de Whisper ggml-{args.modelo}.bin. Descargalo en la carpeta modelos/ "
                 "de la herramienta (el LEEME dice como).")
    if args.publicar and not args.ensayo and not os.environ.get("ZERNIO_API_KEY"):
        sys.exit("--publicar necesita ZERNIO_API_KEY (o usa --ensayo para ver que mandaria)")
    if args.publicar and not args.cuentas:
        sys.exit("--publicar necesita --cuentas plataforma:idDeCuenta (o ZERNIO_CUENTAS)")
    fuente = buscar_fuente()
    if not args.calidad:
        args.calidad = ("720p60/720p/best[height<=720]/best" if canal_twitch(args.url)
                        else "bv*[height<=720]+ba/b[height<=720]/best")

    salida, buf = Path(args.salida).resolve(), Path(args.trabajo).resolve()
    salida.mkdir(parents=True, exist_ok=True)
    if buf.exists():
        shutil.rmtree(buf)
    buf.mkdir(parents=True)

    parar = threading.Event()
    cont = Contador()
    canal = canal_twitch(args.url)
    if canal:
        threading.Thread(target=chat_twitch, args=(canal, cont, parar), daemon=True).start()
    else:
        r = subprocess.run(["yt-dlp", "--print", "id", "--no-warnings", "--playlist-items", "1", args.url],
                           capture_output=True, text=True, timeout=60)
        vid = (r.stdout.strip().splitlines() or [""])[0]
        if not vid:
            sys.exit("No he podido sacar el directo de YouTube: " + r.stderr[-200:])
        threading.Thread(target=chat_youtube, args=(vid, cont, parar), daemon=True).start()

    log("abriendo el directo...")
    urls = resolver(args.url, args.calidad)
    ff = lanzar_buffer(urls, buf)
    t_ini = time.time()
    fin = t_ini + args.minutos * 60
    log(f"vigilando {args.minutos:g} min; ventana {args.ventana:g}s, k={args.k}, minimo {args.min_mensajes} mensajes")

    hist, clips, hilos, n_clip = [], [], [], 0
    json_path = salida / "clips.json"
    lock = threading.Lock()
    reinicios = 0
    proxima = t_ini + args.ventana
    ult_pico = 0.0

    def trabajo(n, t_pico, cuenta, media, desv):
        t_detect = time.time()
        # esperar a que el bufer cubra el "despues" y se cierre el trozo
        while time.time() < t_pico + args.despues + SEG + 1:
            time.sleep(0.5)
        nombre = f"clip-{n:02d}-{datetime.fromtimestamp(t_pico).strftime('%H%M%S')}.mp4"
        destino = salida / nombre
        try:
            dicho = hacer_clip(buf, t_pico - args.antes, t_pico + args.despues, destino, args, fuente)
        except Exception as e:
            log(f"clip {n}: ERROR {e}")
            return
        listo = time.time()
        reg = {"archivo": nombre, "hora": datetime.fromtimestamp(t_pico).isoformat(timespec="seconds"),
               "mensajes_en_ventana": cuenta, "normal_media": round(media, 1), "normal_desviacion": round(desv, 1),
               "duracion_s": round(ffprobe_dur(destino), 1), "texto_dicho": dicho,
               "segundos_desde_el_pico": round(listo - t_pico, 1)}
        if args.publicar:
            try:
                reg["zernio"] = publicar_clip(destino, dicho, args)
            except Exception as e:
                reg["zernio_error"] = str(e)
                log(f"clip {n}: no publicado: {e}")
        with lock:
            clips.append(reg)
            clips.sort(key=lambda r: r["archivo"])
            json_path.write_text(json.dumps(clips, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"clip {n} LISTO: {nombre} ({reg['segundos_desde_el_pico']}s despues del pico) :: {dicho[:80]}")

    try:
        while time.time() < fin and n_clip < args.max_clips:
            time.sleep(0.5)
            if ff.poll() is not None:
                if reinicios >= 3:
                    log("el video se ha cortado (¿acabo el directo?); termino")
                    break
                reinicios += 1
                log("video cortado, reintento", reinicios, ff.stderr.read().decode()[-200:] if ff.stderr else "")
                time.sleep(3)
                try:
                    ff = lanzar_buffer(resolver(args.url, args.calidad), buf)
                except SystemExit:
                    break
            if time.time() < proxima:
                continue
            a, b = proxima - args.ventana, proxima
            proxima += args.ventana
            podar(buf, args.antes + args.despues + 90)
            cuenta = cont.entre(a, b)
            previa = hist[-args.historia:]
            media = statistics.mean(previa) if previa else 0
            desv = statistics.pstdev(previa) if len(previa) > 1 else 0
            umbral = max(media + args.k * max(desv, 1.0), args.min_mensajes)
            pico = len(hist) >= args.calentamiento and cuenta >= umbral and b - ult_pico > args.enfriamiento
            log(f"ventana: {cuenta:3d} msg | normal {media:5.1f} +- {desv:4.1f} | umbral {umbral:5.1f}"
                + ("  <== PICO" if pico else ""))
            if pico:
                n_clip += 1
                ult_pico = b
                h = threading.Thread(target=trabajo, args=(n_clip, b, cuenta, media, desv))
                h.start()
                hilos.append(h)
                # el pico no debe ensuciar lo "normal"
                hist.append(media)
            else:
                hist.append(cuenta)
        if n_clip == 0:
            log("tiempo cumplido sin picos: prueba a bajar --k o --min-mensajes")
        log("esperando a que terminen los clips pendientes...")
        for h in hilos:
            h.join()
    except KeyboardInterrupt:
        log("parado a mano; termino los clips pendientes")
        for h in hilos:
            h.join()
    finally:
        parar.set()
        ff.terminate()
    log(f"hecho: {len(clips)} clips en {salida}")


if __name__ == "__main__":
    main()
