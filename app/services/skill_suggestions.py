from app.models.user import SkillSuggestionModel

async def save_skill_suggestions(user_id, cv_id, softskills, technical_skills, certifications=None, db=None):
    print("Saving skill suggestions for user:", user_id, "cv:", cv_id)

    certifications = certifications or []

    suggestion_doc = SkillSuggestionModel(
        user_id=user_id,
        cv_id=cv_id,
        softskills_suggestions=softskills,
        technical_skills_suggestions=technical_skills,
        certifications_suggestions=certifications  # <-- added
    ).dict(by_alias=True)

    result = await db["skill_suggestions"].insert_one(suggestion_doc)
    print("Inserted document id:", result.inserted_id)
    return result.inserted_id
