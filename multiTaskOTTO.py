import board
import pwmio
import wifi
import socketpool
import ipaddress
import asyncio
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

# Variables globales para la animación asíncrona
current_angles = {"ll": 90.0, "lf": 90.0, "rl": 90.0, "rf": 90.0}
targets = {"ll": 90, "lf": 90, "rl": 90, "rf": 90}
steps = {"ll": 0.0, "lf": 0.0, "rl": 0.0, "rf": 0.0}

# ==========================================
# 2. CONEXIÓN A RED LOCAL
# ==========================================
mi_ip_fija = ipaddress.IPv4Address("192.168.88.250") 
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
# 3. SERVIDOR WEB ASÍNCRONO
# ==========================================
pool = socketpool.SocketPool(wifi.radio)
server = Server(pool, "/static")

@server.route("/")
def base(request: Request):
    return FileResponse(request, "viewpanel.html", "/")

@server.route("/favicon.ico")
def favicon(request: Request):
    return Response(request, "No icon", status=404)

@server.route("/set_servo")
def set_servo(request: Request):
    motor = request.query_params.get("motor")
    val = request.query_params.get("angle")
    if motor in targets and val is not None:
        targets[motor] = int(val)
        steps[motor] = 0 # Movimiento instantáneo
    return Response(request, "OK")

@server.route("/set_pose")
def set_pose(request: Request):
    for m in ["ll", "lf", "rl", "rf"]:
        val = request.query_params.get(m)
        if val is not None:
            targets[m] = int(val)
        
        spd = request.query_params.get(f"s_{m}")
        speed = int(spd) if spd else 0
        
        if speed > 0:
            steps[m] = (targets[m] - current_angles[m]) / (speed / 20.0)
        else:
            steps[m] = 0
            
    return Response(request, "OK")

# ==========================================
# 4. TAREAS DE ASYNCIO
# ==========================================
async def tarea_servidor_web():
    """Mantiene vivo el panel de control web continuamente"""
    server.start(str(wifi.radio.ipv4_address), port=80)
    print(f"Servidor web en http://{wifi.radio.ipv4_address}")
    while True:
        try:
            server.poll()
        except OSError as e:
            # Separado en múltiples líneas para evitar errores de sintaxis
            numero_error = getattr(e, 'errno', None)
            if numero_error not in (113, 104):
                print("Error de red:", e)
        except Exception as e:
            pass
        
        await asyncio.sleep(0.01)

async def tarea_cinematica():
    """Bucle maestro que actualiza los motores a 50Hz"""
    while True:
        for m in ["ll", "lf", "rl", "rf"]:
            if steps[m] == 0:
                current_angles[m] = targets[m]
            else:
                distancia_faltante = targets[m] - current_angles[m]
                if abs(distancia_faltante) <= abs(steps[m]):
                    current_angles[m] = targets[m]
                    steps[m] = 0
                else:
                    current_angles[m] += steps[m]
            
            # Aplica el movimiento físico
            motores[m].angle = max(0, min(180, int(current_angles[m])))
        
        await asyncio.sleep(0.02)

async def tarea_reconexion():
        """Vigila la conexión y la levanta si se cae"""
        while True:
            if not wifi.radio.ipv4_address:
                print("Conexión perdida. Intentando reconectar a Test-Connet...")
                try:
                    wifi.radio.connect("Test-Connet", "claveSegura")
                    print(f"Reconectado. IP: {wifi.radio.ipv4_address}")
                except Exception:
                    pass # Falla silenciosamente y vuelve a intentar en 5 segundos
            await asyncio.sleep(5)

async def main():
        # Lanza las TRES tareas simultáneamente
        await asyncio.gather(tarea_servidor_web(), tarea_cinematica(), tarea_reconexion())

# Inicia el motor de multitarea
asyncio.run(main())