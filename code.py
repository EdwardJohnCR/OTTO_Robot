import time
import board
import pwmio
import wifi
import socketpool
from adafruit_motor import servo
from adafruit_httpserver import Server, Request, Response, FileResponse

    
# ==========================================
# 1. CONFIGURACIÓN DE MOTORES
# ==========================================
pines = {"lf": board.IO5, "ll": board.IO18, "rf": board.IO19, "rl": board.IO23}
motores = {}

current_angles = {}
target_angles = {}
start_angles = {}

for nombre, pin in pines.items():
    pwm = pwmio.PWMOut(pin, duty_cycle=2 ** 15, frequency=50)
    motores[nombre] = servo.Servo(pwm, min_pulse=500, max_pulse=2400)
    motores[nombre].angle = 90
    current_angles[nombre] = 90.0
    target_angles[nombre] = 90.0
    start_angles[nombre] = 90.0

is_moving = False
move_start_time = 0.0
move_duration = 0.5 

# ==========================================
# 2. CONEXIÓN A RED LOCAL (DHCP)
# ==========================================
print("Conectando a 'Test-Connet'...")
try:
    wifi.radio.connect("Test-Connet", "claveSegura")
    print(f"IP asignada: {wifi.radio.ipv4_address}")
except Exception as e:
    print("Error Wi-Fi:", e)

# ==========================================
# 3. SERVIDOR WEB Y RUTAS
# ==========================================
pool = socketpool.SocketPool(wifi.radio)
# La raíz ahora es "/" para que encuentre el index.html suelto
server = Server(pool, "/")

@server.route("/")
def base(request: Request):
    return FileResponse(request, "index.html")

@server.route("/favicon.ico")
def favicon(request: Request):
    return Response(request, "No icon")

@server.route("/set_servo")
def set_servo(request: Request):
    motor = request.query_params.get("motor")
    angle_str = request.query_params.get("angle")
    if motor in pines and angle_str is not None:
        try:
            val = max(0, min(180, int(angle_str)))
            motores[motor].angle = val
            current_angles[motor] = val
            target_angles[motor] = val
        except ValueError: pass
    return Response(request, "OK")

@server.route("/set_pose")
def set_pose(request: Request):
    global is_moving, move_start_time, move_duration
    
    # Mejora de robustez al leer la velocidad
    val_speed = request.query_params.get("speed")
    try:
        speed_ms = int(val_speed) if val_speed else 500
    except ValueError:
        speed_ms = 500
        
    requested_duration = speed_ms / 1000.0
    
    max_diff = 0
    for m in pines.keys():
        val = request.query_params.get(m)
        if val is not None:
            try: 
                target = max(0, min(180, int(val)))
                target_angles[m] = target
                start_angles[m] = current_angles[m]
                
                diff = abs(target - start_angles[m])
                if diff > max_diff:
                    max_diff = diff
            except ValueError: pass

    min_safe_duration = max_diff / 400.0
    
    if requested_duration < min_safe_duration:
        move_duration = min_safe_duration
    else:
        move_duration = requested_duration

    if move_duration <= 0:
        move_duration = 0.01 
        
    move_start_time = time.monotonic()
    is_moving = True
            
    return Response(request, "OK")


# ==========================================
# 4. BUCLE PRINCIPAL (MÁQUINA DE ESTADOS)
# ==========================================
print(f"Servidor en http://{wifi.radio.ipv4_address}")
server.start(str(wifi.radio.ipv4_address), port=80)

while True:
    try:
        server.poll()
    except OSError as e:
        if getattr(e, 'errno', None) in (113, 104): pass
    except Exception as e:
        # Error en la consola!
        print("Error HTTP:", e) 
        
    if is_moving:
        now = time.monotonic()
        elapsed = now - move_start_time
        
        if elapsed >= move_duration:
            for m in pines.keys():
                current_angles[m] = target_angles[m]
                motores[m].angle = current_angles[m]
            is_moving = False
        else:
            progress = elapsed / move_duration
            for m in pines.keys():
                current_angles[m] = start_angles[m] + (target_angles[m] - start_angles[m]) * progress
                motores[m].angle = current_angles[m]
                
    time.sleep(0.005)
    