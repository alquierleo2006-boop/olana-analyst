//! Couche native : fenêtre flottante, zone de notification, raccourci global et moteur d'analyse local.
//! Le presse-papiers n'est lu QUE lorsque l'utilisateur déclenche le raccourci.
//! Aucune clé privée, aucune signature : l'application est en lecture seule.

use std::io::Write;
use std::net::TcpListener;
use std::sync::Mutex;

use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, RunEvent, State, WindowEvent};
use tauri_plugin_clipboard_manager::ClipboardExt;
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

struct Backend {
    url: String,
    token: String,
    sidecar: Mutex<Option<CommandChild>>,
    dev_child: Mutex<Option<std::process::Child>>,
}

#[derive(Default)]
struct CurrentShortcut(Mutex<Option<Shortcut>>);

#[tauri::command]
fn backend_config(state: State<'_, Backend>) -> serde_json::Value {
    serde_json::json!({ "url": state.url, "token": state.token })
}

#[tauri::command]
fn set_shortcut(app: AppHandle, accelerator: String, current: State<'_, CurrentShortcut>) -> Result<(), String> {
    let shortcut: Shortcut = accelerator
        .parse()
        .map_err(|e| format!("raccourci invalide « {accelerator} » : {e}"))?;
    let gs = app.global_shortcut();
    let mut cur = current.0.lock().unwrap();
    if let Some(old) = cur.take() {
        let _ = gs.unregister(old);
    }
    gs.on_shortcut(shortcut, |app, _sc, event| {
        if event.state == ShortcutState::Pressed {
            on_shortcut(app);
        }
    })
    .map_err(|e| format!("raccourci indisponible (déjà utilisé par une autre application ?) : {e}"))?;
    *cur = Some(shortcut);
    Ok(())
}

fn show_window(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
    }
}

fn on_shortcut(app: &AppHandle) {
    show_window(app);
    // Lecture ponctuelle et volontaire du presse-papiers.
    let text = app.clipboard().read_text().unwrap_or_default();
    let text: String = text.chars().take(500).collect();
    let _ = app.emit("shortcut-triggered", text);
}

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(8765)
}

fn log_file(app: &AppHandle) -> Option<std::fs::File> {
    let dir = app.path().app_log_dir().ok()?;
    std::fs::create_dir_all(&dir).ok()?;
    std::fs::OpenOptions::new().create(true).append(true).open(dir.join("backend.log")).ok()
}

fn start_backend(app: &AppHandle) -> Backend {
    let port = free_port();
    let token = uuid::Uuid::new_v4().simple().to_string();
    let url = format!("http://127.0.0.1:{port}");
    let data_dir = app.path().app_data_dir().ok().map(|p| p.to_string_lossy().to_string()).unwrap_or_default();
    // Deux éditions installables côte à côte : l'identifiant de l'application choisit l'édition du moteur.
    let edition = if app.config().identifier.ends_with(".tech") { "tech" } else { "scalp" };
    let envs = [
        ("ANALYST_PORT", port.to_string()),
        ("ANALYST_TOKEN", token.clone()),
        ("ANALYST_DATA_DIR", data_dir),
        ("ANALYST_EDITION", edition.to_string()),
    ];

    // Mode développement : ANALYST_BACKEND_DIR pointe vers le dossier backend (Python installé requis).
    if let Ok(dir) = std::env::var("ANALYST_BACKEND_DIR") {
        let python = std::env::var("ANALYST_PYTHON").unwrap_or_else(|_| if cfg!(windows) { "python".into() } else { "python3".into() });
        let child = std::process::Command::new(python)
            .args(["-m", "analyst"])
            .current_dir(dir)
            .envs(envs.iter().map(|(k, v)| (*k, v.as_str())))
            .spawn()
            .ok();
        return Backend { url, token, sidecar: Mutex::new(None), dev_child: Mutex::new(child) };
    }

    // Mode installé : moteur d'analyse empaqueté (sidecar).
    let mut sidecar_child = None;
    match app.shell().sidecar("analyst-backend") {
        Ok(cmd) => {
            let mut cmd = cmd;
            for (k, v) in envs.iter() {
                cmd = cmd.env(k, v);
            }
            match cmd.spawn() {
                Ok((mut rx, child)) => {
                    sidecar_child = Some(child);
                    let mut log = log_file(app);
                    tauri::async_runtime::spawn(async move {
                        while let Some(ev) = rx.recv().await {
                            if let (Some(f), CommandEvent::Stdout(l) | CommandEvent::Stderr(l)) = (log.as_mut(), &ev) {
                                let _ = f.write_all(l);
                                let _ = f.write_all(b"\n");
                            }
                        }
                    });
                }
                Err(e) => eprintln!("échec du démarrage du moteur d'analyse : {e}"),
            }
        }
        Err(e) => eprintln!("moteur d'analyse introuvable : {e}"),
    }
    Backend { url, token, sidecar: Mutex::new(sidecar_child), dev_child: Mutex::new(None) }
}

fn stop_backend(app: &AppHandle) {
    if let Some(b) = app.try_state::<Backend>() {
        if let Some(c) = b.sidecar.lock().unwrap().take() {
            let _ = c.kill();
        }
        if let Some(mut c) = b.dev_child.lock().unwrap().take() {
            let _ = c.kill();
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| show_window(app)))
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .manage(CurrentShortcut::default())
        .setup(|app| {
            let handle = app.handle().clone();
            let backend = start_backend(&handle);
            app.manage(backend);

            let show = MenuItem::with_id(app, "show", "Afficher / masquer", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quitter", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;
            TrayIconBuilder::with_id("main-tray")
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip(app.config().product_name.clone().unwrap_or_else(|| "Solana AI Desktop Analyst".into()))
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => toggle(app),
                    "quit" => {
                        stop_backend(app);
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
                        toggle(tray.app_handle());
                    }
                })
                .build(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            // Fermer la fenêtre la masque : l'application reste disponible dans la zone de notification.
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .invoke_handler(tauri::generate_handler![backend_config, set_shortcut])
        .build(tauri::generate_context!())
        .expect("erreur au démarrage de l'application");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            stop_backend(handle);
        }
    });
}

fn toggle(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        if w.is_visible().unwrap_or(false) {
            let _ = w.hide();
        } else {
            show_window(app);
        }
    }
}
