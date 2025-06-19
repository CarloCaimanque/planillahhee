# Importa las librerías necesarias
from flask import Flask, request, render_template
import pdfplumber
import re
from datetime import datetime, time, timedelta

# Inicializa la aplicación Flask
app = Flask(__name__)

# --- Feriados Dinámicos ---
def calcular_semana_santa(year):
    """Calcula la fecha del Viernes y Sábado Santo para un año específico."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    domingo_pascua = datetime(year, month, day)
    viernes_santo = domingo_pascua - timedelta(days=2)
    return {viernes_santo.strftime('%d/%m/%Y')}

def get_feriados_por_ano(years):
    """Genera un set con los feriados para cada año solicitado."""
    feriados_totales = set()
    feriados_fijos = {
        "01/01", "01/05", "21/05", "20/06", "16/07", "15/08",
        "18/09", "19/09", "31/10", "01/11", "08/12", "25/12"
    }
    for year in years:
        # Añadir feriados fijos para el año
        for dia_mes in feriados_fijos:
            feriados_totales.add(f"{dia_mes}/{year}")
        # Añadir feriados de Semana Santa
        feriados_totales.update(calcular_semana_santa(year))
    return feriados_totales

DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

def extraer_horarios(pdf_stream):
    """Extrae los horarios de un archivo PDF."""
    registros_dict = {}
    regex_hora = r'(\d{2}:\d{2})'
    try:
        with pdfplumber.open(pdf_stream) as pdf:
            for page in pdf.pages:
                texto_pagina = page.extract_text()
                if not texto_pagina: continue
                lineas = texto_pagina.split('\n')
                for linea in lineas:
                    fecha_match = re.search(r'\b(\d{2}/\d{2}/\d{4})\b', linea)
                    horas_matches = re.findall(regex_hora, linea)
                    if fecha_match and len(horas_matches) >= 4:
                        fecha_actual = fecha_match.group(1)
                        if fecha_actual not in registros_dict:
                            registros_dict[fecha_actual] = {
                                "Fecha": fecha_actual, "Entrada Programada": horas_matches[0],
                                "Salida Programada": horas_matches[1], "Entrada Realizada": horas_matches[2],
                                "Salida Realizada": horas_matches[3]
                            }
        if not registros_dict: return []
        return sorted(list(registros_dict.values()), key=lambda r: datetime.strptime(r['Fecha'], '%d/%m/%Y'))
    except Exception as e:
        print(f"Ocurrió un error al procesar el PDF: {e}")
        return []

def procesar_registros(registros_pdf):
    """
    Función central que procesa todos los registros, identifica todas las
    incidencias y calcula horas extra.
    """
    if not registros_pdf:
        return [], [], [], []

    filas_calculadas = []
    atrasos_salidas = []
    inasistencias_injustificadas = []
    
    registros_map = {reg['Fecha']: reg for reg in registros_pdf}
    fechas_dt = [datetime.strptime(reg['Fecha'], '%d/%m/%Y') for reg in registros_pdf]
    fecha_inicio = min(fechas_dt)
    fecha_fin = max(fechas_dt)
    
    anos_en_pdf = {fecha.year for fecha in fechas_dt}
    feriados_del_periodo = get_feriados_por_ano(anos_en_pdf)
    
    fecha_actual = fecha_inicio
    while fecha_actual <= fecha_fin:
        fecha_str = fecha_actual.strftime('%d/%m/%Y')
        dia_semana_index = fecha_actual.weekday()
        dia_semana_nombre = DIAS_SEMANA[dia_semana_index]
        es_feriado = fecha_str in feriados_del_periodo
        
        calculo = None

        if fecha_str in registros_map:
            reg = registros_map[fecha_str]
            entrada_prog_limpia = re.sub(r'\D', '', reg["Entrada Programada"])
            salida_prog_limpia = re.sub(r'\D', '', reg["Salida Programada"])
            entrada_real_limpia = re.sub(r'\D', '', reg["Entrada Realizada"])
            salida_real_limpia = re.sub(r'\D', '', reg["Salida Realizada"])

            es_inasistencia_ceros = (dia_semana_index < 5 and not es_feriado and
                                     entrada_prog_limpia == "0000" and salida_prog_limpia == "0000" and
                                     entrada_real_limpia == "0000" and salida_real_limpia == "0000")

            # NUEVA LÓGICA PARA HORARIOS PROGRAMADOS ESPECÍFICOS PARA INASISTENCIA
            es_horario_programado_injustificado = (
                dia_semana_index < 5 and not es_feriado and
                (
                    (reg["Entrada Programada"] == "07:30" and reg["Salida Programada"] == "15:30") or
                    (reg["Entrada Programada"] == "07:30" and reg["Salida Programada"] == "16:30")
                )
            )

            if es_inasistencia_ceros or es_horario_programado_injustificado:
                detalle_inasistencia = "Inasistencia (campos en 00:00)"
                if es_horario_programado_injustificado:
                    # Modificado: Simplificamos el detalle para que diga solo "Inasistencia"
                    detalle_inasistencia = "Inasistencia" 
                inasistencias_injustificadas.append({"fecha": fecha_str, "detalle": detalle_inasistencia})
                calculo = crear_fila_incidencia(fecha_str, dia_semana_nombre, es_inasistencia=True)
            else:
                es_atraso = (entrada_prog_limpia == "0930")
                es_salida_antes = (salida_prog_limpia == "1200")
                requiere_justificacion = es_atraso or es_salida_antes
                
                if requiere_justificacion:
                    detalle = "Atraso" if es_atraso and not es_salida_antes else "Salida Antes" if es_salida_antes and not es_atraso else "Atraso y Salida Antes"
                    atrasos_salidas.append({"fecha": fecha_str, "detalle": detalle})
                
                calculo = crear_fila_normal(reg, dia_semana_nombre, requiere_justificacion, es_feriado)
        else:
            if dia_semana_index < 5 and not es_feriado:
                inasistencias_injustificadas.append({"fecha": fecha_str, "detalle": "Inasistencia (día no registrado)"})
                calculo = crear_fila_incidencia(fecha_str, dia_semana_nombre, es_inasistencia=True)
        
        if calculo:
            filas_calculadas.append(calculo)
            
        fecha_actual += timedelta(days=1)
        
    return filas_calculadas, atrasos_salidas, inasistencias_injustificadas

def crear_fila_normal(reg, dia_semana, requiere_justificacion, es_feriado):
    """Crea un diccionario para una fila con datos de horarios."""
    calculo = {
        "fecha": reg["Fecha"], "dia_semana": dia_semana,
        "programado": {"entrada": reg["Entrada Programada"], "salida": reg["Salida Programada"]},
        "extra_diurno": {"desde": "", "hasta": ""}, "extra_nocturno": {"desde": "", "hasta": ""},
        "extra_festivo": {"desde": "", "hasta": ""}, "requiere_justificacion": requiere_justificacion,
        "es_inasistencia": False, "es_feriado": es_feriado
    }
    try:
        entrada_prog = datetime.strptime(reg["Entrada Programada"].strip(), '%H:%M').time()
        salida_prog = datetime.strptime(reg["Salida Programada"].strip(), '%H:%M').time()
        salida_real = datetime.strptime(reg["Salida Realizada"].strip(), '%H:%M').time()
        
        if (entrada_prog == time(0, 0) and salida_prog == time(0, 0) and not requiere_justificacion) or es_feriado:
            calculo["extra_festivo"]["desde"] = reg["Entrada Realizada"]
            calculo["extra_festivo"]["hasta"] = reg["Salida Realizada"]
        elif salida_real > salida_prog:
            calculo["extra_diurno"]["desde"] = reg["Salida Programada"]
            if salida_real <= time(21, 0):
                calculo["extra_diurno"]["hasta"] = reg["Salida Realizada"]
            else:
                calculo["extra_diurno"]["hasta"] = time(21, 0).strftime('%H:%M')
                calculo["extra_nocturno"]["desde"] = time(21, 0).strftime('%H:%M')
                calculo["extra_nocturno"]["hasta"] = reg["Salida Realizada"]
    except ValueError:
        pass
    return calculo

def crear_fila_incidencia(fecha, dia_semana, es_inasistencia=False):
    """Crea un diccionario para una fila de inasistencia."""
    return {
        "fecha": fecha, "dia_semana": dia_semana,
        "programado": {"entrada": "—", "salida": "—"},
        "extra_diurno": {"desde": "—", "hasta": "—"}, "extra_nocturno": {"desde": "—", "hasta": "—"},
        "extra_festivo": {"desde": "—", "hasta": "—"}, "requiere_justificacion": False,
        "es_inasistencia": es_inasistencia, "es_feriado": False
    }

def calcular_totales(filas):
    """Calcula la suma total de horas extra."""
    total_diurno, total_nocturno, total_festivo = timedelta(), timedelta(), timedelta()
    def get_diff(desde_str, hasta_str):
        if not desde_str or desde_str == "—": return timedelta()
        try:
            dt_desde = datetime.strptime(desde_str, '%H:%M')
            dt_hasta = datetime.strptime(hasta_str, '%H:%M')
            if dt_hasta < dt_desde: dt_hasta += timedelta(days=1)
            return dt_hasta - dt_desde
        except ValueError: return timedelta()

    for fila in filas:
        total_diurno += get_diff(fila['extra_diurno']['desde'], fila['extra_diurno']['hasta'])
        total_nocturno += get_diff(fila['extra_nocturno']['desde'], fila['extra_nocturno']['hasta'])
        total_festivo += get_diff(fila['extra_festivo']['desde'], fila['extra_festivo']['hasta'])
    
    def format_timedelta(td):
        total_seconds = td.total_seconds()
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        return f"{hours:02}:{minutes:02}"

    return {"diurno": format_timedelta(total_diurno), "nocturno": format_timedelta(total_nocturno), "festivo": format_timedelta(total_festivo)}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/procesar', methods=['POST'])
def procesar():
    if 'archivo_pdf' not in request.files:
        return render_template('index.html', error="No se encontró el archivo PDF.")
    archivo = request.files['archivo_pdf']
    if archivo.filename == '':
        return render_template('index.html', error="No se seleccionó ningún archivo.")
    if archivo:
        registros_extraidos = extraer_horarios(archivo.stream)
        if not registros_extraidos:
             return render_template('index.html', error="No se encontraron registros con formato válido en el PDF.")
        
        filas_calculadas, atrasos_salidas, inasistencias = procesar_registros(registros_extraidos)
        totales = calcular_totales(filas_calculadas)
        
        return render_template('index.html', filas=filas_calculadas, totales=totales, 
                               atrasos_salidas=atrasos_salidas, inasistencias=inasistencias)

    return render_template('index.html', error="Error desconocido al procesar el archivo.")

if __name__ == '__main__':
    app.run(debug=True, port=5001)







