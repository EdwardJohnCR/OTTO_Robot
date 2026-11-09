"""
CEREBRO DE OTTO - CIRCUITPYTHON (No Bloqueante)
Este código convierte la IdeaBoard en un servidor web que controla 4 servos y 1 buzzer.
Su mayor ventaja es que usa una "Máquina de Estados": nunca se congela, 
pudiendo mover motores, emitir sonidos y escuchar WiFi al mismo tiempo.
"""

import time
import board
import pwmio
import wifi
import socketpool
from adafruit_motor import servo
from adafruit_httpserver import Server, Request, Response, FileResponse

# ==========================================
# 1. CONFIGURACIÓN DE LAS PIERNAS (SERVOMOTORES)
# ==========================================
# Diccionario con los pines de los motores: Left Leg (ll), Left Foot (lf), etc.
pines = {"lf": board.IO5, "ll": board.IO18, "rf": board.IO19, "rl": board.IO23}
motores = {}

# Estas tres variables son el secreto del movimiento suave:
current_angles = {} # Dónde está el servo físicamente en este instante
target_angles = {}  # A dónde queremos que llegue
start_angles = {}   # De dónde arrancó el movimiento

# Configuramos cada motor uno por uno
for nombre, pin in pines.items():
    # Creamos la señal eléctrica (PWM) a 50Hz, que es el estándar para servos SG90
    pwm = pwmio.PWMOut(pin, duty_cycle=2 ** 15, frequency=50)
    motores[nombre] = servo.Servo(pwm, min_pulse=500, max_pulse=2400)
    
    # Ponemos a Otto en posición de descanso (90 grados) al encender
    motores[nombre].angle = 90
    current_angles[nombre] = 90.0
    target_angles[nombre] = 90.0
    start_angles[nombre] = 90.0

# Variables de control de tiempo para saber cuándo empezar y terminar un movimiento
is_moving = False
move_start_time = 0.0
move_duration = 0.5 

# ==========================================
# 2. CONFIGURACIÓN DE LA VOZ (BUZZER PASIVO)
# ==========================================
# Usamos el Pin 32 porque es seguro para salidas de señal analógica/PWM
pin_buzzer = board.IO32 
buzzer_active = False
buzzer_end_time = 0.0
buzzer = None 

try:
    # variable_frequency=True nos permite cambiar las notas musicales (Hz) sobre la marcha
    buzzer = pwmio.PWMOut(pin_buzzer, frequency=1000, duty_cycle=0, variable_frequency=True)
    print("Buzzer activado correctamente en Pin 32.")
except Exception as e:
    print("Aviso: El buzzer no pudo iniciar.", e)

# ==========================================
# 3. CONEXIÓN A RED LOCAL (WIFI)
# ==========================================
print("Conectando a 'Test-Connet'...")
try:
    # Nos conectamos al router Mikrotik. Él nos dará una IP Dinámica (DHCP) automáticamente
    wifi.radio.connect("Test-Connet", "claveSegura")
    print(f"IP asignada: {wifi.radio.ipv4_address}")
except Exception as e:
    print("Error Wi-Fi:", e)

# ==========================================
# 4. SERVIDOR WEB Y "PUERTAS DE ENTRADA" (RUTAS)
# ==========================================
pool = socketpool.SocketPool(wifi.radio)
server = Server(pool, "/") # La carpeta raíz donde está nuestro index.html

@server.route("/")
def base(request: Request):
    # Cuando el navegador entra a la IP, le enviamos el panel de control HTML
    return FileResponse(request, "index.html")

@server.route("/favicon.ico")
def favicon(request: Request):
    # Evita errores cuando el navegador pide el icono de la pestaña
    return Response(request, "No icon")

@server.route("/set_servo")
def set_servo(request: Request):
    # Esta ruta mueve un solo motor de golpe (se usa en los sliders del control manual)
    motor = request.query_params.get("motor")
    angle_str = request.query_params.get("angle")
    if motor in pines and angle_str is not None:
        try:
            # max() y min() son un muro de seguridad para no romper los motores (0 a 180)
            val = max(0, min(180, int(angle_str)))
            motores[motor].angle = val
            current_angles[motor] = val
            target_angles[motor] = val
        except ValueError: pass
    return Response(request, "OK")

@server.route("/set_pose")
def set_pose(request: Request):
    # Esta ruta planifica un movimiento suave de todo el cuerpo
    global is_moving, move_start_time, move_duration
    
    val_speed = request.query_params.get("speed")
    try:
        speed_ms = int(val_speed) if val_speed else 500
    except ValueError:
        speed_ms = 500
        
    requested_duration = speed_ms / 1000.0 # Convertimos milisegundos a segundos
    
    # PASO A: Averiguar cuál motor tiene que viajar más lejos
    max_diff = 0
    for m in pines.keys():
        val = request.query_params.get(m)
        if val is not None:
            try: 
                target = max(0, min(180, int(val)))
                target_angles[m] = target
                start_angles[m] = current_angles[m]
                
                # Calculamos cuántos grados viajará este motor
                diff = abs(target - start_angles[m])
                if diff > max_diff:
                    max_diff = diff
            except ValueError: pass

    # PASO B: Límite de Velocidad Físico (Protección)
    # Un SG90 viaja seguro a unos 400 grados por segundo. 
    # Calculamos el tiempo mínimo en el que es seguro hacer este viaje.
    min_safe_duration = max_diff / 400.0
    
    # Si la web pide ir más rápido de lo seguro, forzamos a ir al límite seguro.
    if requested_duration < min_safe_duration:
        move_duration = min_safe_duration
    else:
        move_duration = requested_duration

    if move_duration <= 0:
        move_duration = 0.01 
        
    # PASO C: ¡Dar la orden de arranque!
    move_start_time = time.monotonic() # Tomamos la hora exacta de inicio
    is_moving = True # Le decimos al Bucle Principal que empiece a caminar
            
    return Response(request, "OK")

@server.route("/beep")
def beep(request: Request):
    # Esta ruta planifica un sonido
    global buzzer_active, buzzer_end_time
    try:
        freq = int(request.query_params.get("f", 1000))
        dur = int(request.query_params.get("d", 200))
        
        if freq > 0 and buzzer is not None:
            buzzer.frequency = freq
            # duty_cycle a la mitad (32768) significa volumen máximo
            buzzer.duty_cycle = 32768  
            # Calculamos a qué hora exacta debe apagarse
            buzzer_end_time = time.monotonic() + (dur / 1000.0)
            buzzer_active = True
        elif buzzer is not None:
            buzzer.duty_cycle = 0 # 0 es apagar volumen
            buzzer_active = False
    except ValueError:
        pass
    return Response(request, "OK")

# ==========================================
# 5. EL CORAZÓN DE OTTO: BUCLE PRINCIPAL
# ==========================================
print(f"Servidor listo en http://{wifi.radio.ipv4_address}")
server.start(str(wifi.radio.ipv4_address), port=80)

while True:
    # TAREA 1: Atender Internet
    # Revisa rapidísimo si alguien hizo clic en la página web
    try:
        server.poll()
    except OSError as e:
        if getattr(e, 'errno', None) in (113, 104): pass
    except Exception as e:
        print("Error HTTP:", e) 
        
    # TAREA 2: Mover Músculos (Interpolación)
    if is_moving:
        now = time.monotonic()
        elapsed = now - move_start_time # ¿Cuánto tiempo ha pasado desde que empezamos?
        
        if elapsed >= move_duration:
            # Ya se acabó el tiempo, forzamos los motores a su meta exacta
            for m in pines.keys():
                current_angles[m] = target_angles[m]
                motores[m].angle = current_angles[m]
            is_moving = False # Detenemos el movimiento
        else:
            # Aún estamos viajando. Calculamos qué porcentaje del viaje llevamos (ej: 0.5 = 50%)
            progress = elapsed / move_duration
            for m in pines.keys():
                # Matemática: Posición Actual = Inicio + (Distancia Total * Porcentaje)
                current_angles[m] = start_angles[m] + (target_angles[m] - start_angles[m]) * progress
                motores[m].angle = current_angles[m]
                
    # TAREA 3: Controlar la Voz
    # Revisa si la alarma de tiempo del sonido ya sonó para apagar el buzzer
    if buzzer_active and buzzer is not None and time.monotonic() >= buzzer_end_time:
        buzzer.duty_cycle = 0 # Mutear
        buzzer_active = False
                
    # Micro-descanso de 5 milisegundos para no sobrecalentar el procesador WiFi
    time.sleep(0.005)