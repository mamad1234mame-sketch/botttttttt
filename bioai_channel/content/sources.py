"""منابع علمی که به عنوان «زمینه» به مدل داده می‌شوند.

دو کاربرد:
۱) در پرامپت به مدل گفته می‌شود از این دامنه‌ها نقل‌قول کند (Grounding با
   Google Search هم این‌ها را می‌بیند).
۲) در جست‌وجوی مستقیمِ سیگنال‌ها (PubMed / bioRxiv / Trends) استفاده می‌شود.
"""

from __future__ import annotations

#: دامنه‌هایی که به عنوان منبع معتبر اولویت دارند.
PREFERRED_DOMAINS: tuple[str, ...] = (
    "nature.com",
    "science.org",
    "cell.com",
    "thelancet.com",
    "nejm.org",
    "biorxiv.org",
    "medrxiv.org",
    "arxiv.org",
    "pubmed.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov",
    "europepmc.org",
    "elifesciences.org",
    "pnas.org",
    "genomebiology.biomedcentral.com",
    "genome.cshlp.org",
    "nar.oxfordjournals.org",
    "academic.oup.com",
    "cellpress.com",
    "science.sciencemag.org",
    "ieee.org",
    "acm.org",
    "openreview.net",
    "proceedings.mlr.press",
    "proceedings.neurips.cc",
)

#: منابع رسمی ابزارها و دیتاست‌ها.
TOOL_AND_DATA_DOMAINS: tuple[str, ...] = (
    "github.com",
    "gitlab.com",
    "bioconda.github.io",
    "bio.tools",
    "uniprot.org",
    "rcsb.org",
    "alphafold.ebi.ac.uk",
    "ensembl.org",
    "ucsc.edu",
    "ebi.ac.uk",
    "sanger.ac.uk",
    "gnomad.broadinstitute.org",
    "gtexportal.org",
    "depmap.org",
    "cellxgene.cziscience.com",
    "singlecell.broadinstitute.org",
    "huggingface.co",
    "pypi.org",
    "cran.r-project.org",
)

#: گروه‌های پژوهشی پیشتاز و دامنهٔ رسمی‌شان (برای قالب lab_watch).
TOP_LABS: dict[str, str] = {
    "Google DeepMind": "deepmind.google",
    "Broad Institute": "broadinstitute.org",
    "EMBL-EBI": "ebi.ac.uk",
    "Wellcome Sanger Institute": "sanger.ac.uk",
    "Chan Zuckerberg Biohub": "czbiohub.org",
    "Whitehead Institute": "wi.mit.edu",
    "Helmholtz Munich": "helmholtz-munich.de",
    "Max Planck Institute": "mpg.de",
    "Institut Pasteur": "pasteur.fr",
    "ETH Zürich": "ethz.ch",
    "MIT (CSAIL / Koch Institute)": "mit.edu",
    "Stanford University": "stanford.edu",
    "Harvard University": "harvard.edu",
    "UCSF": "ucsf.edu",
    "Rockefeller University": "rockefeller.edu",
    "Cold Spring Harbor Laboratory": "cshl.edu",
    "NIH / NHGRI": "genome.gov",
    "RIKEN": "riken.jp",
    "Tsinghua University": "tsinghua.edu.cn",
    "KAIST": "kaist.ac.kr",
    "Weizmann Institute": "weizmann.ac.il",
    "University of Oxford": "ox.ac.uk",
    "University of Cambridge": "cam.ac.uk",
    "Karolinska Institutet": "ki.se",
    "University of Toronto / Vector Institute": "vectorinstitute.ai",
    "Allen Institute": "alleninstitute.org",
    "HHMI Janelia Research Campus": "janelia.org",
    "The Francis Crick Institute": "crick.ac.uk",
    "ISB (Institute for Systems Biology)": "systemsbiology.org",
    "EPFL": "epfl.ch",
}

#: کلیدواژه‌هایی که برای گرفتن سیگنال‌های تازه از PubMed استفاده می‌شوند.
PUBMED_QUERIES: tuple[str, ...] = (
    "(artificial intelligence OR machine learning OR deep learning) AND (protein structure OR protein design)",
    "(foundation model OR large language model) AND (genomics OR single-cell OR transcriptomics)",
    "(bioinformatics OR computational biology) AND (new method OR benchmark OR pipeline)",
    "(AI OR machine learning) AND (drug discovery OR molecular docking OR ADMET)",
    "(spatial transcriptomics OR single-cell RNA-seq) AND (deep learning OR graph neural network)",
)

#: دسته‌های bioRxiv که هر روز بررسی می‌شوند.
#: توجه: API نام دسته را انسان‌خوان و با فاصله برمی‌گرداند
#: (مثلاً «synthetic biology»)، نه با خط تیره. این فهرست با پاسخ واقعی
#: https://api.biorxiv.org/details/biorxiv/... مطابقت داده شده است.
BIORXIV_CATEGORIES: tuple[str, ...] = (
    "bioinformatics",
    "genomics",
    "synthetic biology",
    "biophysics",
    "bioengineering",
    "molecular biology",
    "systems biology",
)

#: دامنه‌هایی که هیچ‌وقت به عنوان منبع علمی نقل نشوند.
EXCLUDED_DOMAINS: tuple[str, ...] = (
    "pinterest.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "quora.com",
    "reddit.com",
    "wikipedia.org",  # برای استناد علمی نه، هرچند برای زمینه بد نیست
)
