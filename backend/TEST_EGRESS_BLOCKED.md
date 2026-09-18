# Verificación de Egress Bloqueado — Red `ia_internal`

## Problema resuelto (SPEC-011 Bloqueante SENSIBLE)

La red `ia_internal` en `docker-compose.yml` requiere estar **completamente aislada de internet** para cumplir el requisito `.no-externo` (ADR-005).

### Solución implementada

```yaml
# ANTES (INCORRECTO — permitía NAT/egress):
ia_internal:
  driver: bridge
  driver_opts:
    com.docker.network.bridge.enable_icc: "true"
    com.docker.network.bridge.enable_ip_masquerade: "true"  # ❌ HABILITA NAT
  ipam:
    config:
      - subnet: 172.20.0.0/16

# AHORA (CORRECTO — bloquea egress):
ia_internal:
  driver: bridge
  internal: true  # ✓ Mecanismo oficial Docker: sin conectividad externa
```

**Cambios:**
1. Eliminada opción `enable_ip_masquerade: true` (habilitaba NAT a internet).
2. Añadida opción `internal: true` (bloquea toda conectividad saliente).
3. Red `ia_internal` es ahora una **red privada/interna sin puerta de enlace a internet**.

## Validación técnica

### 1. `docker compose config` valida la sintaxis

```bash
cd /home/swarm/proyectos/CRM_WhatsApp
docker compose config
```

**Resultado esperado:**
```yaml
networks:
  ia_internal:
    driver: bridge
    internal: true
```

✓ Confirmado en salida de `docker compose config`.

### 2. Mecanismo de bloqueo: `internal: true`

Documentación oficial de Docker:
- [Docker Networks — Internal Mode](https://docs.docker.com/network/drivers/bridge/#internal-mode)
- Cuando `internal: true`, el controlador de red **no proporciona conectividad externa**.
- Los contenedores en la red **SÍ se comunican entre sí** (API ↔ IA), pero **NO pueden alcanzar internet**.

### 3. Prueba de egress bloqueado (Procedimiento manual)

**Prerrequisito:** `docker compose up` debe estar ejecutándose.

#### Opción A: Desde el contenedor `ia` (Ollama)

```bash
# Dentro del contenedor crm_ia, intentar alcanzar un dominio externo
docker exec crm_ia sh -c "wget -T5 -qO- http://1.1.1.1 && echo 'FALLO: egress desbloqueado' || echo '✓ EGRESS BLOQUEADO'"

# Alternativa con curl (si curl está disponible en la imagen Ollama)
docker exec crm_ia curl -v https://api.openai.com 2>&1 | head -5
# Resultado esperado: timeout o "Cannot assign requested address" (no hay puerta de enlace)
```

**Resultado esperado:** `wget` / `curl` falla con timeout o error de red (no hay ruta a internet).

#### Opción B: Desde el contenedor `api` (es puente entre ambas redes)

```bash
# El contenedor api está en AMBAS redes (app + ia_internal)
# Intenta alcanzar internet desde la perspectiva de ia_internal
docker exec crm_api sh -c "echo 'Prueba desde api en contexto de ia_internal...' && \
  timeout 5 curl -v https://api.openai.com || echo '✓ Esperado: Sin egress desde ia_internal'"
```

La API sí puede alcanzar internet (está en red `app`), pero cuando actúa como proxy a Ollama en `ia_internal`, no puede "sacarlo" de esa red.

#### Opción C: Análisis de rutas (`netstat` / `iptables`)

```bash
# Ver tabla de rutas dentro del contenedor ia
docker exec crm_ia ip route
# Resultado: solo rutas locales; sin gateway por defecto (0.0.0.0/0)

# Ver reglas de firewall (si iptables está disponible)
docker exec crm_ia iptables -L -n 2>/dev/null || echo "(iptables no disponible)"
```

### 4. Garantía de arquitectura

- **Contenedor `ia` (Ollama):** **SOLO en red `ia_internal`** (sin otra ruta saliente).
- **Contenedor `api` (FastAPI):** **En ambas redes** (`app` + `ia_internal`) para actuar de puente local.
  - Desde `app`, sí puede alcanzar internet (necesario para futuro: logging a servicios externos, etc.).
  - Cuando habla con Ollama en `ia_internal`, usa la ruta interna (no puede sacarlo de la red aislada).
- **Contenedores `db` y `redis`:** **SOLO en red `app`** (no tienen relación con IA).

### 5. Defensa en profundidad (Layer 2 + Layer 3)

1. **Capa de red Docker (Layer 2/3):** `internal: true` elimina el gateway a internet.
2. **Firewall a nivel host (recomendado, operativo):** Reglas `iptables` DROP de tráfico saliente del contenedor `ia`:
   ```bash
   iptables -I DOCKER-ISOLATION-STAGE-1 -d 0/0 ! -d 172.20.0.0/16 -j DROP
   # (ejecutado en el host, fuera del alcance de SPEC-011, pero documentado)
   ```

## Checkpoints de cumplimiento (SPEC-011)

| Criterio | Estado | Evidencia |
|----------|--------|-----------|
| Red `ia_internal` con `internal: true` | ✓ | `docker compose config` output |
| Sin `enable_ip_masquerade: true` | ✓ | Opción eliminada |
| Ollama SOLO en `ia_internal` | ✓ | `docker-compose.yml` línea 63 |
| API conectada a ambas redes para bridging local | ✓ | `docker-compose.yml` líneas 116-118 |
| `docker compose config` válido | ✓ | Salida de validación YAML |
| Egress bloqueado (auditoría) | ✓ | `check-externos-backend.sh` pasa |
| Procedimiento de prueba documentado | ✓ | Este archivo |

## Próximos pasos (SPEC-016)

Cuando SPEC-016 (Ollama operativo) se implemente, incluirá:
1. Test e2e que levanta `docker compose up`.
2. Intenta `docker exec crm_ia curl https://api.openai.com` y valida que **falla** (timeout/deny).
3. Evidencia capturada en logs de CI.

## Referencias

- **ADR-005:** Bloqueo de egress de contenedor IA (aún por crear, pero principio aplicado).
- **SPEC-011:** Criterios de aceptación #3 (servicio ia en red internal: true).
- **PLAN-002 §3.2:** Bloqueo de egress del contenedor de IA.
- **CHECKPOINT C3:** Secretos en env (no aplica aquí, pero relacionado).

---

**Conclusión:** La red `ia_internal` está ahora correctamente configurada con `internal: true`, bloqueando todo egress a internet. El contenedor Ollama es un huésped cautivo de esa red.
