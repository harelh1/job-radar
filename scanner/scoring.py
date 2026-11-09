"""Match score (0-100) between a job and Harel's profile.

Profile (from the CV): 4th-year B.Sc. Electro-Optical Engineering student; Zemax OpticStudio, physical/geometrical optics, lasers, photodetectors,
interferometry, optics lab equipment, MATLAB, Python. Final project: interferometry +
signal processing. Open to student jobs (2-3 days/week) and full-time junior roles,
anywhere in Israel, including defense (clearance OK).

Score = how well the role's field fits (title counts most, description adds)
       + how well the seniority fits a student / new grad
       - penalties for unrelated fields and heavy experience requirements.
Every rule that fires adds a short Hebrew reason, shown next to the score.
"""
import re

# (regex, points, hebrew reason) - checked against the TITLE
TITLE_FIELD = [
    (r"electro[\s-]?optic|אלקטרו[\s-]?אופט|\bE\.?O\.?\b", 45, "אלקטרו-אופטיקה בכותרת"),
    (r"optic|optical|אופטי|אופטיקה|photonic|פוטוני", 40, "אופטיקה/פוטוניקה בכותרת"),
    (r"laser|לייזר|lidar|ליידר", 38, "לייזרים/LiDAR"),
    (r"interferomet|spectro|ספקטר|metrolog|מטרולוג", 36, "מטרולוגיה/אינטרפרומטריה"),
    (r"physic|פיזיק", 32, "פיזיקה"),
    (r"imaging|camera|מצלמ|image sensor|detector|גלאי|infrared|\bIR\b|thermal|night vision|דימות", 30, "דימות/גלאים/מצלמות"),
    (r"(?:system|systems|מערכת|מערכות)[\s-]*(?:engineer|מהנדס)", 20, "הנדסת מערכות"),
    (r"(?:test|validation|verification|integration|בדיקות|אינטגרציה|ולידציה)", 16, "בדיקות/אינטגרציה"),
    (r"r\s*&\s*d|research|מחקר|פיתוח|algorithm|אלגוריתם|signal processing|עיבוד אותות|עיבוד תמונה|image processing|computer vision", 14, "מו\"פ/אלגוריתמים/עיבוד אותות"),
    (r"semiconductor|מוליכים|wafer|process engineer|yield|inspection", 14, "מוליכים למחצה"),
    (r"hardware|חומרה|sensor|חיישן|application engineer|field engineer|lab|מעבדה", 10, "חומרה/מעבדה"),
]

# keywords in the DESCRIPTION (each counted once, capped)
DESC_SKILLS = [
    (r"zemax|opticstudio|code v|lighttools", 10, "Zemax"),
    (r"electro[\s-]?optic|אלקטרו[\s-]?אופט", 7, "רקע אלקטרו-אופטי"),
    (r"optic|אופטי", 5, None),
    (r"laser|לייזר", 5, None),
    (r"interferomet|אינטרפרומ", 7, "אינטרפרומטריה"),
    (r"photodetector|detector|גלאי|photodiode|receiver", 4, None),
    (r"matlab", 5, "MATLAB"),
    (r"python", 4, "Python"),
    (r"lab(?:oratory)? (?:equipment|work|experience)|hands[\s-]on|optical (?:bench|setup)|מעבדה", 4, "עבודת מעבדה"),
    (r"physical optics|wave optics|fourier optics|diffraction|polariz", 5, None),
    (r"signal processing|עיבוד אותות", 3, None),
    (r"electro[\s-]?optics?(?: engineering)? (?:student|degree)|b\.?sc\.? in (?:electro|optic|physics)", 6, "דורש בדיוק את התואר שלך"),
]

STUDENT = r"student|סטודנט|intern\b|internship|התמחות|graduate|new grad|בוגר|entry[\s-]level|ללא ניסיון"
JUNIOR = r"junior|ג'וניור|גוניור|jr\.?\b"
SENIOR = r"senior|sr\.|בכיר|lead\b|leader|ראש צוות|manager|מנהל|director|principal|staff|head of|vp\b|architect|ארכיטקט|expert|מומחה"
ADVANCED_DEGREE_ONLY = r"(?:m\.?sc|ph\.?d|master'?s|doctoral|תואר שני|דוקטורט)[^.]{0,40}(?:student|סטודנט)"

UNRELATED = (r"sales|account manager|marketing|שיווק|מכירות|finance|accountant|חשב|controller|payroll|"
             r"\bhr\b|human resources|recruit|גיוס|legal|lawyer|עו\"ד|procurement|רכש|buyer|logistic|לוגיסטיקה|"
             r"secretary|מזכיר|admin|office manager|customer success|support specialist|"
             r"front[\s-]?end|back[\s-]?end|full[\s-]?stack|devops|web developer|mobile developer|"
             r"data analyst|bi developer|\bit\b|helpdesk|cyber|security analyst|technician|טכנאי|operator|מפעיל|"
             r"warehouse|driver|נהג|cook|chef|clinical|nurse|regulatory|quality assurance (?:specialist|manager)|"
             r"\bpcb\b layout|accounting|tax|payable|receivable|executive assistant|project manager|program manager|"
             r"product manager|mechanical engineer|מהנדס מכונות|civil|construction|electrician|חשמלאי")


def _years_required(text):
    yrs = [int(n) for n in re.findall(r"(\d{1,2})\s*\+?\s*(?:years|yrs|שנות|שנים)", text, re.I) if 0 < int(n) < 30]
    return max(yrs) if yrs else 0


def score(job):
    title = job.get("title", "")
    desc = (job.get("description") or "")[:12000]
    dept = job.get("department", "") or ""
    head = f"{title} {dept}"
    s, reasons = 0, []

    # 1) field fit from title (best match + small bonus for a second one)
    hits = [(p, r) for rx, p, r in TITLE_FIELD if re.search(rx, title, re.I)]
    if hits:
        hits.sort(key=lambda x: -x[0])
        s += hits[0][0] + (min(8, hits[1][0] // 3) if len(hits) > 1 else 0)
        reasons.append(hits[0][1])
    elif re.search("|".join(rx for rx, _, _ in TITLE_FIELD[:6]), dept, re.I):
        s += 18
        reasons.append("מחלקה אופטית/פיזיקלית")

    # 2) skills in description (cap 30)
    sk = 0
    for rx, p, r in DESC_SKILLS:
        if re.search(rx, desc, re.I):
            sk += p
            if r and r not in reasons:
                reasons.append(r)
    s += min(30, sk)

    # 3) seniority / role type
    is_student = bool(re.search(STUDENT, head, re.I))
    if is_student:
        s += 22
        reasons.insert(0, "משרת סטודנט")
        if re.search(ADVANCED_DEGREE_ONLY, title + " " + desc[:3000], re.I) and not re.search(r"b\.?sc|bachelor|תואר ראשון", desc, re.I):
            s -= 15
            reasons.append("מיועד לתואר שני/דוקטורט")
        if re.search(r"(?:\d|two|three|שלוש|שני|יומיים)[^.]{0,15}(?:days|ימים)|part[\s-]?time|משרה חלקית|חצי משרה|20[\s-]?(?:hours|שעות)", desc, re.I):
            s += 3
    elif re.search(JUNIOR, head, re.I):
        s += 15
        reasons.insert(0, "משרת ג'וניור")
    elif re.search(SENIOR, title, re.I):
        s -= 30
        reasons.append("משרה בכירה")

    yrs = _years_required(desc)
    if not is_student:
        if yrs >= 5:
            s -= 25; reasons.append(f"דורש {yrs}+ שנות ניסיון")
        elif yrs >= 3:
            s -= 15; reasons.append(f"דורש {yrs}+ שנות ניסיון")
        elif yrs >= 1:
            s -= 4
        elif not re.search(SENIOR, title, re.I):
            s += 6  # no experience requirement found

    # 4) unrelated field
    if re.search(UNRELATED, title, re.I) and (not hits or hits[0][0] < 30):
        s -= 35
        reasons.append("תחום פחות רלוונטי")

    # technician / production roles are below an engineering degree
    if re.search(r"technician|טכנאי|practical engineer|הנדסאי|operator|מפעיל|עובד.?ת? ייצור|production worker|assembler|מרכיב", title, re.I):
        s -= 22
        reasons.append("משרת טכנאי/הנדסאי")
    # advanced-degree roles
    if re.search(r"ph\.?d|m\.?sc|master'?s|דוקטורט|תואר שני|postdoc", title, re.I):
        s -= 18
        reasons.append("מיועד לתואר מתקדם")

    # 5) clearance is fine (he's open to defense) - just note it
    if re.search(r"security clearance|סיווג ביטחוני|סיווג", desc, re.I):
        reasons.append("דורש סיווג ביטחוני")

    pct = max(1, min(98, round(s * 100 / 105)))
    return pct, reasons[:5], ("student" if is_student else "full")
