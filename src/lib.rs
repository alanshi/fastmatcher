use pyo3::prelude::*;
use aho_corasick::AhoCorasick;

#[pyclass]
#[derive(Clone)]
pub struct MatchInfo {
    #[pyo3(get)]
    pub keyword: String,
    #[pyo3(get)]
    pub line_no: usize,
    #[pyo3(get)]
    pub line_text: String,
}

#[pyclass]
pub struct ACMatcher {
    ac: AhoCorasick,
    patterns: Vec<String>,
    with_lineno: bool,
}

#[pymethods]
impl ACMatcher {
    #[new]
    pub fn new(patterns: Vec<String>, ignore_case: bool, with_lineno: bool) -> Self {
        let ac = if ignore_case {
            AhoCorasick::builder()
                .ascii_case_insensitive(true)
                .build(&patterns)
                .unwrap()
        } else {
            AhoCorasick::new(&patterns).unwrap()
        };

        ACMatcher {
            ac,
            patterns,
            with_lineno,
        }
    }

    pub fn search(&self, py: Python<'_>, text: &str) -> PyResult<PyObject> {
        if !self.with_lineno {
            // 高速模式：仅关键词
            let mut out = Vec::<String>::new();
            for m in self.ac.find_iter(text) {
                out.push(self.patterns[m.pattern()].clone());
            }
            return Ok(out.into_py(py));
        }

        // 行号模式
        let mut results = Vec::<MatchInfo>::new();

        for (i, line) in text.lines().enumerate() {
            for m in self.ac.find_iter(line) {
                results.push(MatchInfo {
                    keyword: self.patterns[m.pattern()].clone(),
                    line_no: i + 1,
                    line_text: line.to_string(),
                });
            }
        }

        Ok(results.into_py(py))
    }
}

#[pymodule]
fn fastmatcher(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<ACMatcher>()?;
    m.add_class::<MatchInfo>()?;
    Ok(())
}
