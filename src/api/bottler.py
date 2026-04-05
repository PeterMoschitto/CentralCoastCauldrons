from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, field_validator
from typing import List
from src.api import auth
import sqlalchemy
from src import database as db

router = APIRouter(
    prefix="/bottler",
    tags=["bottler"],
    dependencies=[Depends(auth.get_api_key)],
)


class PotionMixes(BaseModel):
    potion_type: List[int] = Field(
        ...,
        min_length=4,
        max_length=4,
        description="Must contain exactly 4 elements: [r, g, b, d]",
    )
    quantity: int = Field(
        ..., ge=1, le=10000, description="Quantity must be between 1 and 10,000"
    )

    @field_validator("potion_type")
    @classmethod
    def validate_potion_type(cls, potion_type: List[int]) -> List[int]:
        if sum(potion_type) != 100:
            raise ValueError("Sum of potion_type values must be exactly 100")
        return potion_type


@router.post("/deliver/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def post_deliver_bottles(potions_delivered: List[PotionMixes], order_id: int):
    """
    Delivery of potions requested after plan. order_id is a unique value representing
    a single delivery; the call is idempotent based on the order_id.
    """
    print(f"potions delivered: {potions_delivered} order_id: {order_id}")

    with db.engine.begin() as connection:
        for potion in potions_delivered:
            ml_used = potion.quantity * 100

            if potion.potion_type == [100, 0, 0, 0]:
                connection.execute(
                    sqlalchemy.text(
                        """
                        UPDATE global_inventory
                        SET red_ml = red_ml - :ml_used,
                            red_potions = red_potions + :quantity
                        """
                    ),
                    {"ml_used": ml_used, "quantity": potion.quantity},
                )

            elif potion.potion_type == [0, 100, 0, 0]:
                connection.execute(
                    sqlalchemy.text(
                        """
                        UPDATE global_inventory
                        SET green_ml = green_ml - :ml_used,
                            green_potions = green_potions + :quantity
                        """
                    ),
                    {"ml_used": ml_used, "quantity": potion.quantity},
                )

            elif potion.potion_type == [0, 0, 100, 0]:
                connection.execute(
                    sqlalchemy.text(
                        """
                        UPDATE global_inventory
                        SET blue_ml = blue_ml - :ml_used,
                            blue_potions = blue_potions + :quantity
                        """
                    ),
                    {"ml_used": ml_used, "quantity": potion.quantity},
                )


def create_bottle_plan(
    red_ml: int,
    green_ml: int,
    blue_ml: int,
    dark_ml: int,
    maximum_potion_capacity: int,
    current_potion_inventory: List[PotionMixes],
) -> List[PotionMixes]:
    plan: List[PotionMixes] = []

    # num potions that can be made
    red_quantity = red_ml // 100
    green_quantity = green_ml // 100
    blue_quantity = blue_ml // 100

    # make potions 
    if red_quantity > 0:
        plan.append(
            PotionMixes(
                potion_type=[100, 0, 0, 0],
                quantity=red_quantity,
            )
        )

    if green_quantity > 0:
        plan.append(
            PotionMixes(
                potion_type=[0, 100, 0, 0],
                quantity=green_quantity,
            )
        )

    if blue_quantity > 0:
        plan.append(
            PotionMixes(
                potion_type=[0, 0, 100, 0],
                quantity=blue_quantity,
            )
        )

    return plan


@router.post("/plan", response_model=List[PotionMixes])
def get_bottle_plan():
    """
    Gets the plan for bottling potions.
    Each bottle has a quantity of what proportion of red, green, blue, and dark potions to add.
    Colors are expressed in integers from 0 to 100 that must sum up to exactly 100.
    """

    with db.engine.begin() as connection:
        row = connection.execute(
            sqlalchemy.text(
                """
                SELECT red_ml, green_ml, blue_ml
                FROM global_inventory
                """
            )
        ).one()

        current_red_ml = row.red_ml
        current_green_ml = row.green_ml
        current_blue_ml = row.blue_ml

    # TODO: Fill in values below based on what is in your database
    return create_bottle_plan(
        red_ml=current_red_ml,
        green_ml=current_green_ml,
        blue_ml=current_blue_ml,
        dark_ml=0,
        maximum_potion_capacity=50,
        current_potion_inventory=[],
    )


if __name__ == "__main__":
    print(get_bottle_plan())
