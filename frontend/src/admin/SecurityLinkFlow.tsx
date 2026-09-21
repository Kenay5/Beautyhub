import { FormEvent, useEffect, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";

type TotpSetup = {
  provisioningUri: string;
  manualKey: string;
};

type FlowState =
  | { kind: "loading" }
  | { kind: "invalid"; message: string }
  | { kind: "ready"; totpSetup: TotpSetup }
  | { kind: "recovery"; recoveryCodes: readonly string[] }
  | { kind: "complete" };

type ActivationStep = 1 | 2 | 3 | 4 | 5;

type SecurityLinkFlowProps = {
  token: string | null;
  endpointPrefix?: string;
};

const activationSteps = [
  "Cuenta",
  "Contraseña",
  "Seguridad (TOTP)",
  "Recuperación",
  "¡Listo!",
] as const;
const genericLinkMessage = "Este enlace no es válido o ya no está disponible.";
const invalidPasswordMessage = "La contraseña no cumple los requisitos de seguridad.";

export function SecurityLinkFlow({ token, endpointPrefix = "/api/admin/security-links" }: SecurityLinkFlowProps) {
  const [state, setState] = useState<FlowState>(token === null ? { kind: "invalid", message: genericLinkMessage } : { kind: "loading" });
  const [step, setStep] = useState<ActivationStep>(1);
  const [password, setPassword] = useState("");
  const [passwordConfirmation, setPasswordConfirmation] = useState("");
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [showManualKey, setShowManualKey] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const sensitiveSetup = useRef<TotpSetup | null>(null);

  useEffect(() => {
    if (token === null) return;

    const controller = new AbortController();
    void prepareSecurityLink(endpointPrefix, token, controller.signal)
      .then((totpSetup) => {
        sensitiveSetup.current = totpSetup;
        setState({ kind: "ready", totpSetup });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        sensitiveSetup.current = null;
        setState({ kind: "invalid", message: genericLinkMessage });
      });

    return () => {
      controller.abort();
      sensitiveSetup.current = null;
    };
  }, [endpointPrefix, token]);

  function continueFromPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const validationError = validatePassword(password, passwordConfirmation);
    if (validationError !== null) {
      setPasswordError(validationError);
      return;
    }
    setPasswordError(null);
    setStep(3);
  }

  async function completeActivation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (token === null || !/^\d{6}$/.test(totpCode) || isSubmitting) return;
    setIsSubmitting(true);
    try {
      const recoveryCodes = await completeActivationRequest(endpointPrefix, {
        token,
        password,
        totpCode,
      });
      sensitiveSetup.current = null;
      setPassword("");
      setPasswordConfirmation("");
      setTotpCode("");
      setShowManualKey(false);
      setState({ kind: "recovery", recoveryCodes });
      setStep(4);
    } catch (error: unknown) {
      sensitiveSetup.current = null;
      setPassword("");
      setPasswordConfirmation("");
      setTotpCode("");
      setShowManualKey(false);
      setState({
        kind: "invalid",
        message: error instanceof ActivationCompletionError && error.kind === "invalid_password"
          ? invalidPasswordMessage
          : genericLinkMessage,
      });
    } finally {
      setIsSubmitting(false);
    }
  }

  function finishRecoveryCodeDisplay() {
    setState({ kind: "complete" });
    setStep(5);
  }

  async function leaveSecureFlow(event: React.MouseEvent<HTMLAnchorElement>) {
    event.preventDefault();
    const activeToken = token;
    sensitiveSetup.current = null;
    setPassword("");
    setPasswordConfirmation("");
    setTotpCode("");
    setState({ kind: "invalid", message: genericLinkMessage });
    if (activeToken !== null) {
      await abandonSecurityLink(endpointPrefix, activeToken);
    }
    window.location.assign("/admin/");
  }

  return (
    <main className="activation-page">
      <header className="activation-header">
        <img className="activation-brand" src="/assets/brand/logo.jpeg" alt="Manita de Gato, salón de belleza" />
        <div>
          <h1>Activación administrativa</h1>
          <p>Configura tu cuenta en unos simples pasos para comenzar.</p>
        </div>
      </header>

      <ol className="activation-progress" aria-label="Progreso de activación">
        {activationSteps.map((label, index) => {
          const number = index + 1;
          const current = (state.kind === "ready" || state.kind === "recovery" || state.kind === "complete") && number === step;
          return (
            <li className={current ? "activation-progress__item activation-progress__item--current" : "activation-progress__item"} aria-current={current ? "step" : undefined} key={label}>
              <span>{number}</span>
              <small>{label}</small>
            </li>
          );
        })}
      </ol>

      <section className="activation-card" aria-labelledby="activation-card-title">
        {state.kind === "loading" ? (
          <>
            <p className="activation-eyebrow">Acceso seguro</p>
            <h2 id="activation-card-title">Verificando tu enlace</h2>
            <p role="status">Espera un momento…</p>
          </>
        ) : null}

        {state.kind === "invalid" ? (
          <>
            <p className="activation-eyebrow">Acceso seguro</p>
            <h2 id="activation-card-title">
              {state.message === invalidPasswordMessage ? "Contraseña no aceptada" : "Enlace no disponible"}
            </h2>
            <p className="activation-notice activation-notice--error" role="alert">{state.message}</p>
          </>
        ) : null}

        {state.kind === "ready" && step === 1 ? (
          <>
            <p className="activation-eyebrow">Paso 1 de 5</p>
            <h2 id="activation-card-title">Activa tu cuenta</h2>
            <p className="activation-lead">Completa tu contraseña y vincula una aplicación de autenticación para proteger el acceso administrativo.</p>
            <div className="activation-notice" role="note">Este enlace es personal y de un solo uso. No lo compartas con nadie.</div>
            <button className="activation-button" type="button" onClick={() => setStep(2)}>Continuar</button>
          </>
        ) : null}

        {state.kind === "ready" && step === 2 ? (
          <form className="activation-form" onSubmit={continueFromPassword}>
            <p className="activation-eyebrow">Paso 2 de 5</p>
            <h2 id="activation-card-title">Crea tu contraseña</h2>
            <p className="activation-lead">Elige una contraseña segura para tu cuenta.</p>
            <label className="activation-field" htmlFor="new-password">
              Nueva contraseña
              <input id="new-password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required value={password} aria-describedby="password-hint password-error" onChange={(event) => setPassword(event.target.value)} />
            </label>
            <label className="activation-field" htmlFor="confirm-password">
              Confirmar contraseña
              <input id="confirm-password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required value={passwordConfirmation} aria-describedby="password-hint password-error" onChange={(event) => setPasswordConfirmation(event.target.value)} />
            </label>
            <p className="activation-notice" id="password-hint">Usa entre 12 y 128 caracteres. Puedes pegar una frase o usar tu administrador de contraseñas.</p>
            {passwordError !== null ? <p className="activation-error" id="password-error" role="alert">{passwordError}</p> : <span id="password-error" />}
            <button className="activation-button" type="submit">Continuar</button>
          </form>
        ) : null}

        {state.kind === "ready" && step === 3 ? (
          <form className="activation-form activation-form--totp" onSubmit={(event) => void completeActivation(event)}>
            <p className="activation-eyebrow">Paso 3 de 5</p>
            <h2 id="activation-card-title">Protege tu cuenta</h2>
            <p className="activation-lead">Escanea el código con una aplicación de autenticación compatible.</p>
            <div className="activation-qr">
              <QRCodeSVG aria-label="Código QR para configurar la aplicación de autenticación" role="img" size={220} value={state.totpSetup.provisioningUri} />
            </div>
            <button className="activation-link-button" type="button" aria-expanded={showManualKey} onClick={() => setShowManualKey((current) => !current)}>
              {showManualKey ? "Ocultar clave manual" : "Mostrar clave manual"}
            </button>
            {showManualKey ? <output className="totp-setup__manual-key" aria-label="Clave manual de autenticación">{formatManualKey(state.totpSetup.manualKey)}</output> : null}
            <label className="activation-field" htmlFor="totp-code">
              Código de 6 dígitos
              <input id="totp-code" type="text" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required value={totpCode} onChange={(event) => setTotpCode(event.target.value.replace(/\D/g, "").slice(0, 6))} />
            </label>
            <p className="activation-notice">El código cambia cada 30 segundos. Ingresa el código actual de tu aplicación.</p>
            <button className="activation-button" type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Activando cuenta…" : "Activar cuenta"}
            </button>
          </form>
        ) : null}

        {state.kind === "recovery" ? (
          <div className="activation-form">
            <p className="activation-eyebrow">Paso 4 de 5</p>
            <h2 id="activation-card-title">Guarda tus códigos de recuperación</h2>
            <p className="activation-lead">Estos códigos se muestran una sola vez. Guárdalos fuera de este dispositivo en un lugar seguro.</p>
            <ul className="activation-recovery-codes" aria-label="Códigos de recuperación">
              {state.recoveryCodes.map((code) => <li key={code}><code>{code}</code></li>)}
            </ul>
            <div className="activation-notice" role="note">Cada código funciona una sola vez. Nunca los compartas ni los guardes junto con tu contraseña.</div>
            <button className="activation-button" type="button" onClick={finishRecoveryCodeDisplay}>Ya guardé mis códigos</button>
          </div>
        ) : null}

        {state.kind === "complete" ? (
          <div className="activation-complete">
            <p className="activation-eyebrow">Paso 5 de 5</p>
            <div className="activation-complete__icon" aria-hidden="true">✓</div>
            <h2 id="activation-card-title">Cuenta activada</h2>
            <p className="activation-lead">Tu contraseña y verificación en dos pasos quedaron configuradas. Por seguridad, inicia sesión con tus nuevos factores.</p>
            <a className="activation-button activation-button--link" href="/admin/">Ir al inicio de sesión</a>
          </div>
        ) : null}

        {state.kind === "loading" || state.kind === "invalid" || state.kind === "ready" ? (
          <a className="activation-exit" href="/admin/" onClick={(event) => void leaveSecureFlow(event)}>Salir del flujo seguro</a>
        ) : null}
      </section>
    </main>
  );
}

function validatePassword(password: string, confirmation: string): string | null {
  if (password.length < 12 || password.length > 128 || password.trim().length === 0) {
    return "La contraseña debe contener entre 12 y 128 caracteres y no puede estar formada solo por espacios.";
  }
  if (password !== confirmation) return "Las contraseñas no coinciden.";
  return null;
}

function formatManualKey(value: string): string {
  return value.match(/.{1,4}/g)?.join(" ") ?? value;
}

async function prepareSecurityLink(endpointPrefix: string, token: string, signal: AbortSignal): Promise<TotpSetup> {
  const response = await fetch(`${endpointPrefix}/prepare`, {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    referrerPolicy: "no-referrer",
    body: JSON.stringify({ token }),
    signal,
  });
  if (!response.ok) throw new Error("security link is unavailable");
  const value: unknown = await response.json();
  if (!isPreparedFlow(value)) throw new Error("security link response is invalid");
  return value.totpSetup;
}

async function abandonSecurityLink(endpointPrefix: string, token: string): Promise<void> {
  try {
    await fetch(`${endpointPrefix}/abandon`, {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      keepalive: true,
      headers: { "Content-Type": "application/json" },
      referrerPolicy: "no-referrer",
      body: JSON.stringify({ token }),
    });
  } catch {
    // Link expiry remains the final cleanup boundary if navigation wins.
  }
}

function isPreparedFlow(value: unknown): value is { totpSetup: TotpSetup } {
  if (typeof value !== "object" || value === null || !("totpSetup" in value)) return false;
  const setup = value.totpSetup;
  if (typeof setup !== "object" || setup === null) return false;
  if (!("provisioningUri" in setup) || !("manualKey" in setup)) return false;
  return typeof setup.provisioningUri === "string" && setup.provisioningUri.startsWith("otpauth://totp/") && typeof setup.manualKey === "string" && setup.manualKey.length > 0;
}

class ActivationCompletionError extends Error {
  constructor(readonly kind: "invalid_password" | "unavailable") {
    super("owner activation could not be completed");
  }
}

async function completeActivationRequest(endpointPrefix: string, values: {
  token: string;
  password: string;
  totpCode: string;
}): Promise<readonly string[]> {
  const response = await fetch(`${endpointPrefix}/complete`, {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    referrerPolicy: "no-referrer",
    body: JSON.stringify(values),
  });
  if (!response.ok) {
    throw new ActivationCompletionError(response.status === 422 ? "invalid_password" : "unavailable");
  }
  const payload: unknown = await response.json();
  if (!isRecoveryCodeResponse(payload)) {
    throw new ActivationCompletionError("unavailable");
  }
  return payload.recoveryCodes;
}

function isRecoveryCodeResponse(value: unknown): value is { recoveryCodes: string[] } {
  if (typeof value !== "object" || value === null || !("recoveryCodes" in value)) return false;
  const codes = value.recoveryCodes;
  return Array.isArray(codes)
    && codes.length === 10
    && new Set(codes).size === 10
    && codes.every((code) => typeof code === "string" && /^[A-HJ-NP-Z2-9]{4}(?:-[A-HJ-NP-Z2-9]{4}){3}$/.test(code));
}
