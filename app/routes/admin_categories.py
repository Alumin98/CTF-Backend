"""Admin endpoints for managing challenge categories."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.category import Category
from app.routes.admin_challenges import require_admin
from app.schemas import CategoryCreate, CategoryRead, CategoryUpdate

router = APIRouter(prefix="/admin/categories", tags=["Admin: Categories"])


@router.post("", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
) -> CategoryRead:
    existing = await db.execute(select(Category).where(Category.name == payload.name))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Category name already exists")

    category = Category(name=payload.name, description=payload.description)
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return CategoryRead.model_validate(category)


@router.get("", response_model=List[CategoryRead])
async def list_categories(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
) -> List[CategoryRead]:
    rows = await db.execute(select(Category).order_by(Category.name))
    return [CategoryRead.model_validate(cat) for cat in rows.scalars().all()]


@router.get("/{category_id}", response_model=CategoryRead)
async def get_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
) -> CategoryRead:
    category = await db.get(Category, category_id)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    return CategoryRead.model_validate(category)


@router.patch("/{category_id}", response_model=CategoryRead)
async def update_category(
    category_id: int,
    payload: CategoryUpdate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
) -> CategoryRead:
    category = await db.get(Category, category_id)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")

    if payload.name and payload.name != category.name:
        existing = await db.execute(select(Category).where(Category.name == payload.name))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Category name already exists")
        category.name = payload.name

    if payload.description is not None:
        category.description = payload.description

    await db.commit()
    await db.refresh(category)
    return CategoryRead.model_validate(category)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
) -> None:
    category = await db.get(Category, category_id)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")

    await db.delete(category)
    await db.commit()
    return None
