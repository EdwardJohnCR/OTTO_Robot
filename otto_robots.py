import time
import board
import pwmio
import wifi
import socketpool
import ipaddress
from adafruit_motor import servo
from adafruit_httpserver import Server, Request, Response, FileResponse

# ==========================================
# 1. CONFIGURACIÓN DE MOTORES
# ==========================================
pines = {"lf": board.IO5, "ll": board.IO18, "rf": board.IO19, "rl": board.IO23}
motores = {}
for nombre, pin in pines.items():
    pwm = pwmio.PWMOut(pin, duty_cycle=2 ** 15, frequency=50)
    motores[nombre] = servo.Servo(pwm, min_pulse=500, max_pulse=2400)
    motores[nombre].angle = 90

# ==========================================
# 2. CONEXIÓN A RED LOCAL
# ==========================================
mi_ip_fija = ipaddress.IPv4Address("192.168.88.246") 
mascara = ipaddress.IPv4Address("255.255.255.0")
puerta_enlace = ipaddress.IPv4Address("192.168.88.1") 

wifi.radio.set_ipv4_address(ipv4=mi_ip_fija, netmask=mascara, gateway=puerta_enlace)
print("Conectando a 'Test-Connet'...")
try:
    wifi.radio.connect("Test-Connet", "claveSegura")
    print(f"Conectado exitosamente. IP: {wifi.radio.ipv4_address}")
except Exception as e:
    print("Error al conectar al Wi-Fi:", e)

# ==========================================
# 3. SERVIDOR WEB Y RUTAS
# ==========================================
pool = socketpool.SocketPool(wifi.radio)
server = Server(pool, "/static")

@server.route("/")
def base(request: Request):
    return FileResponse(request, "index.html", "/")

@server.route("/favicon.ico")
def favicon(request: Request):
    return Response(request, "No icon", status=404)

@server.route("/set_servo")
def set_servo(request: Request):
    motor = request.query_params.get("motor")
    angle_str = request.query_params.get("angle")
    if motor in motores and angle_str is not None:
        try: motores[motor].angle = int(angle_str)
        except ValueError: pass
    return Response(request, "OK")

@server.route("/set_pose")
def set_pose(request: Request):
    # 1. Leer los ángulos objetivo
    targets = {}
    for m in ["ll", "lf", "rl", "rf"]:
        val = request.query_params.get(m)
        if val is not None:
            try: targets[m] = int(val)
            except ValueError: pass
    
    # 2. Leer la velocidad solicitada
    speed = 0
    try:
        speed_str = request.query_params.get("speed")
        if speed_str: speed = int(speed_str)
    except ValueError:
        pass

    # 3. Interpolar (Mover suavemente) si la velocidad es > 0
    if speed > 0:
        pasos = 20 # Cantidad de divisiones para el movimiento suave
        delay = (speed / 1000.0) / pasos
        starts = {m: motores[m].angle for m in targets}
        
        for i in range(1, pasos + 1):
            for m, target in targets.items():
                start = starts[m]
                if start is None: start = 90
                # Cálculo lineal del ángulo intermedio
                current = start + (target - start) * (i / pasos)
                # Limitar rangos mecánicos de seguridad
                motores[m].angle = max(0, min(180, current))
            time.sleep(delay)

    # Asegurar posición final exacta
    for m, target in targets.items():
        motores[m].angle = max(0, min(180, target))
        
    return Response(request, "OK")

# ==========================================
# 4. BUCLE PRINCIPAL ROBUSTO
# ==========================================
print(f"Iniciando servidor web en http://{wifi.radio.ipv4_address}")
server.start(str(wifi.radio.ipv4_address), port=80)

while True:
    try:
        server.poll()
    except OSError as e:
        if getattr(e, 'errno', None) in (113, 104): pass
        else: print("Error de Red:", e)
    except Exception as e:
        print("Error HTTP General:", e)