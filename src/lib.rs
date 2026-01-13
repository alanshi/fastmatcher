use pyo3::prelude::*;
use aho_corasick::AhoCorasick;

use std::collections::{HashSet, VecDeque};
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::sync::mpsc::{self, Receiver};
use std::thread;

use rayon::prelude::*;

/// =======================
/// Python 暴露的数据结构
/// =======================

#[pyclass]
#[derive(Debug, Clone)]
pub struct MatchInfo {
    #[pyo3(get)]
    pub line_no: usize,

    #[pyo3(get)]
    pub keywords: Vec<String>,

    #[pyo3(get)]
    pub lines: Vec<String>, // 上下文（含命中行）
}

/// =======================
/// Python Generator
/// =======================

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

/// =======================
/// ACMatcher
/// =======================

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
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?
        } else {
            AhoCorasick::new(&patterns)
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?
        };

        Ok(Self {
            ac,
            patterns,
            context,
        })
    }

    /// 单文件 generator
    pub fn search_file_iter(&self, path: String) -> PyResult<MatchIter> {
        let matcher = self.clone();
        let (tx, rx) = mpsc::channel();

        thread::spawn(move || {
            if let Ok(file) = File::open(&path) {
                let reader = BufReader::new(file);
                matcher.search_reader(reader, tx);
            }
        });

        Ok(MatchIter { rx })
    }

    /// 多文件并行 generator
    pub fn search_files_iter(&self, paths: Vec<String>) -> PyResult<MatchIter> {
        let matcher = self.clone();
        let (tx, rx) = mpsc::channel();

        thread::spawn(move || {
            paths.par_iter().for_each(|path| {
                if let Ok(file) = File::open(path) {
                    let reader = BufReader::new(file);
                    matcher.search_reader(reader, tx.clone());
                }
            });
        });

        Ok(MatchIter { rx })
    }
}

/// =======================
/// 核心匹配逻辑（流式）
/// =======================

impl ACMatcher {
    fn search_reader<R: BufRead>(&self, reader: R, tx: mpsc::Sender<MatchInfo>) {
        let mut prev_lines: VecDeque<String> = VecDeque::new();
        let mut pending: VecDeque<(usize, HashSet<usize>, Vec<String>)> = VecDeque::new();

        let mut line_no = 0;

        for line in reader.lines().flatten() {
            line_no += 1;

            // 1️⃣ 先补齐之前命中的“后文”
            for (_, _, ref mut lines) in pending.iter_mut() {
                if lines.len() < self.context * 2 + 1 {
                    lines.push(line.clone());
                }
            }

            // 2️⃣ 当前行匹配
            let mut hit_patterns = HashSet::<usize>::new();
            for m in self.ac.find_iter(&line) {
                hit_patterns.insert(m.pattern().as_usize());
            }

            if !hit_patterns.is_empty() {
                let mut ctx = Vec::new();

                // 前文
                for l in prev_lines.iter() {
                    ctx.push(l.clone());
                }

                // 当前行
                ctx.push(line.clone());

                pending.push_back((line_no, hit_patterns, ctx));
            }

            // 3️⃣ 输出已完成上下文的命中
            while let Some((_, _, ref ctx)) = pending.front() {
                if ctx.len() >= self.context * 2 + 1 {
                    let (ln, patterns, lines) = pending.pop_front().unwrap();

                    let keywords = patterns
                        .into_iter()
                        .map(|i| self.patterns[i].clone())
                        .collect::<Vec<_>>();

                    let _ = tx.send(MatchInfo {
                        line_no: ln,
                        keywords,
                        lines,
                    });
                } else {
                    break;
                }
            }

            // 4️⃣ 更新前文缓冲
            prev_lines.push_back(line);
            if prev_lines.len() > self.context {
                prev_lines.pop_front();
            }
        }

        // flush 剩余
        for (ln, patterns, lines) in pending {
            let keywords = patterns
                .into_iter()
                .map(|i| self.patterns[i].clone())
                .collect::<Vec<_>>();

            let _ = tx.send(MatchInfo {
                line_no: ln,
                keywords,
                lines,
            });
        }
    }
}

/// =======================
/// Python module
/// =======================

#[pymodule]
fn fastmatcher(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<ACMatcher>()?;
    m.add_class::<MatchInfo>()?;
    m.add_class::<MatchIter>()?;
    Ok(())
}
