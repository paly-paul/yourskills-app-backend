
async def get_cv_summary(parsed_data: dict):
    known = []
    unknown = []

    if parsed_data.get("Education"):
        known.append("Education")
    else:
        unknown.append("Education")

    if parsed_data.get("YearsOfExperience"):
        known.append("Years Of Experience")
    else:
        unknown.append("Years Of Experience")

    skills = parsed_data.get("Skills", {})
    if skills.get("HardSkills"):
        known.append("Hard Skills")
    else:
        unknown.append("Hard Skills")

    if skills.get("SoftSkills"):
        known.append("Soft Skills")
    else:
        unknown.append("Soft Skills")

    if parsed_data.get("Certifications"):
        known.append("Certifications")
    else:
        unknown.append("Certifications")

    if parsed_data.get("Tools"):
        known.append("Tools")
    else:
        unknown.append("Tools")

    if parsed_data.get("Industry"):
        known.append("Industry")
    else:
        unknown.append("Industry")

    return {
        "known": known,
        "unknown": unknown
    }
