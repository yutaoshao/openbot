//! One owner arbitrates native quit, installation, and service retry transitions.
use std::sync::Mutex;

#[derive(Default, PartialEq)]
enum Phase {
    #[default]
    Running,
    Installing,
    Quitting,
    ExitReady,
}

#[derive(Default)]
pub struct Lifecycle(Mutex<Phase>);

impl Lifecycle {
    pub fn request_quit(&self) -> bool {
        let mut phase = self.0.lock().unwrap();
        if *phase != Phase::Running {
            return false;
        }
        *phase = Phase::Quitting;
        true
    }

    pub fn finish_quit(&self) -> bool {
        let mut phase = self.0.lock().unwrap();
        if *phase != Phase::Quitting {
            return false;
        }
        *phase = Phase::ExitReady;
        true
    }

    pub fn exit_ready(&self) -> bool {
        *self.0.lock().unwrap() == Phase::ExitReady
    }

    pub fn begin_install(&self) -> Result<Installation<'_>, String> {
        let mut phase = self.0.lock().unwrap();
        if *phase != Phase::Running {
            return Err("OpenBot is exiting or already installing an update".into());
        }
        *phase = Phase::Installing;
        Ok(Installation(self))
    }

    /// Retry is synchronous. Holding this lock through start prevents a delayed
    /// retry from starting Python after an installation or quit has taken ownership.
    pub fn retry_service<T>(&self, start: impl FnOnce() -> Result<T, String>) -> Result<T, String> {
        let phase = self.0.lock().unwrap();
        if *phase != Phase::Running {
            return Err("OpenBot is exiting or installing an update".into());
        }
        start()
    }
}

pub struct Installation<'a>(&'a Lifecycle);
impl Installation<'_> {
    pub fn complete(self) {
        *self.0 .0.lock().unwrap() = Phase::ExitReady;
    }
}
impl Drop for Installation<'_> {
    fn drop(&mut self) {
        let mut phase = self.0 .0.lock().unwrap();
        if *phase == Phase::Installing {
            *phase = Phase::Running;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Barrier};
    use std::thread;

    #[test]
    fn simultaneous_quit_and_install_have_exactly_one_owner() {
        for _ in 0..32 {
            let lifecycle = Arc::new(Lifecycle::default());
            let start = Arc::new(Barrier::new(3));
            let attempts_finished = Arc::new(Barrier::new(3));
            let quit_state = lifecycle.clone();
            let quit_start = start.clone();
            let quit_finished = attempts_finished.clone();
            let quit = thread::spawn(move || {
                quit_start.wait();
                let owns_quit = quit_state.request_quit();
                quit_finished.wait();
                owns_quit
            });
            let install_state = lifecycle.clone();
            let install_start = start.clone();
            let install_finished = attempts_finished.clone();
            let install = thread::spawn(move || {
                install_start.wait();
                let ownership = install_state.begin_install();
                let owns_install = ownership.is_ok();
                // Keep the installation guard alive until both contenders tried.
                install_finished.wait();
                owns_install
            });
            start.wait();
            attempts_finished.wait();
            assert_ne!(quit.join().unwrap(), install.join().unwrap());
        }
    }

    #[test]
    fn quit_wins_before_the_install_attempt_and_blocks_install_after_cleanup() {
        let lifecycle = Arc::new(Lifecycle::default());
        let quit_started = Arc::new(Barrier::new(2));
        let quitter = lifecycle.clone();
        let signal = quit_started.clone();
        let quit = thread::spawn(move || {
            assert!(quitter.request_quit());
            signal.wait();
        });
        quit_started.wait();
        assert!(lifecycle.begin_install().is_err());
        assert!(!lifecycle.exit_ready());
        assert!(lifecycle.finish_quit());
        assert!(lifecycle.exit_ready());
        assert!(lifecycle.begin_install().is_err());
        quit.join().unwrap();
    }

    #[test]
    fn install_wins_and_every_native_quit_entry_is_refused_until_failure_releases_it() {
        let lifecycle = Arc::new(Lifecycle::default());
        let installing = lifecycle.begin_install().unwrap();
        let start = Arc::new(Barrier::new(4));
        // Dock/RunEvent, menu and desktop_quit all call the same request_quit.
        let quits: Vec<_> = (0..3)
            .map(|_| {
                let shared = lifecycle.clone();
                let signal = start.clone();
                thread::spawn(move || {
                    signal.wait();
                    shared.request_quit()
                })
            })
            .collect();
        start.wait();
        for quit in quits {
            assert!(!quit.join().unwrap());
        }
        assert!(!lifecycle.exit_ready());
        assert!(lifecycle.retry_service(|| Ok(())).is_err());
        drop(installing);
        assert!(lifecycle.request_quit());
    }

    #[test]
    fn successful_install_allows_restart_without_opening_a_quit_race() {
        let lifecycle = Lifecycle::default();
        lifecycle.begin_install().unwrap().complete();
        assert!(lifecycle.exit_ready());
        assert!(!lifecycle.request_quit());
        assert!(lifecycle.begin_install().is_err());
        assert!(lifecycle.retry_service(|| Ok(())).is_err());
    }
}
