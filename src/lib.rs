use pyo3::prelude::*;
use aho_corasick::AhoCorasick;

use std::collections::{HashSet, VecDeque};
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::sync::mpsc::{self, Receiver, Sender};
use std::thread;

use rayon::prelude::*;

#[pyclass]
#[derive(Debug, Clone)]
pub struct MatchInfo {
    #[pyo3(get)]
    pub file_path: String,

    #[pyo3(get)]
    pub line_no: usize,

    #[pyo3(get)]
    pub keywords: Vec<String>,

    #[pyo3(get)]
    pub lines: Vec<String>,
}

#[pyclass]
pub struct MatchIter {
    rx: Receiver<MatchInfo>,
}

#[pymethods]
impl MatchIter {
    fn __iter__(slf: PyRef<Self>) -> PyRef<Self> {
        slf
    }

    fn __next__(&mut self) -> Option<MatchInfo> {
        self.rx.recv().ok()
    }
}

#[pyclass]
#[derive(Clone)]
pub struct ACMatcher {
    ac: AhoCorasick,
    patterns: Vec<String>,
    context: usize,
}

#[pymethods]
impl ACMatcher {
    #[new]
    pub fn new(
        patterns: Vec<String>,
        ignore_case: bool,
        context: usize,
    ) -> PyResult<Self> {
        let ac = if ignore_case {
            AhoCorasick::builder()
                .ascii_case_insensitive(true)
                .build(&patterns)
                .unwrap()
        } else {
            AhoCorasick::new(&patterns).unwrap()
        };

        Ok(Self {
            ac,
            patterns,
            context,
        })
    }

    pub fn search_files_iter(&self, paths: Vec<String>) -> PyResult<MatchIter> {
        let matcher = self.clone();
        let (tx, rx) = mpsc::channel();

        thread::spawn(move || {
            paths.par_iter().for_each(|raw_path| {
                let path = PathBuf::from(raw_path);

                if !path.is_file() {
                    return;
                }

                let file = match File::open(&path) {
                    Ok(f) => f,
                    Err(_) => return,
                };

                let reader = BufReader::new(file);
                let file_path = raw_path.clone();

                matcher.search_reader(reader, file_path, tx.clone());
            });
        });

        Ok(MatchIter { rx })
    }
}

impl ACMatcher {
    fn search_reader<R: BufRead>(
        &self,
        reader: R,
        file_path: String,
        tx: Sender<MatchInfo>,
    ) {
        let mut prev_lines = VecDeque::new();
        let mut pending: VecDeque<(usize, HashSet<usize>, Vec<String>)> = VecDeque::new();

        let mut line_no = 0;

        for line in reader.lines().flatten() {
            line_no += 1;

            for (_, _, ctx) in pending.iter_mut() {
                if ctx.len() < self.context * 2 + 1 {
                    ctx.push(line.clone());
                }
            }

            let mut hits = HashSet::new();
            for m in self.ac.find_iter(&line) {
                hits.insert(m.pattern().as_usize());
            }

            if !hits.is_empty() {
                let mut ctx = prev_lines.iter().cloned().collect::<Vec<_>>();
                ctx.push(line.clone());
                pending.push_back((line_no, hits, ctx));
            }

            while let Some((_, _, ctx)) = pending.front() {
                if ctx.len() >= self.context * 2 + 1 {
                    let (ln, patterns, lines) = pending.pop_front().unwrap();

                    let keywords = patterns
                        .into_iter()
                        .map(|i| self.patterns[i].clone())
                        .collect();

                    let _ = tx.send(MatchInfo {
                        file_path: file_path.clone(),
                        line_no: ln,
                        keywords,
                        lines,
                    });
                } else {
                    break;
                }
            }

            prev_lines.push_back(line);
            if prev_lines.len() > self.context {
                prev_lines.pop_front();
            }
        }

        for (ln, patterns, lines) in pending {
            let keywords = patterns
                .into_iter()
                .map(|i| self.patterns[i].clone())
                .collect();

            let _ = tx.send(MatchInfo {
                file_path: file_path.clone(),
                line_no: ln,
                keywords,
                lines,
            });
        }
    }
}

#[pymodule]
fn fastmatcher(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<ACMatcher>()?;
    m.add_class::<MatchInfo>()?;
    m.add_class::<MatchIter>()?;
    Ok(())
}
