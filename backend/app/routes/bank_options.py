"""Authenticated BANKEX/BANKNIFTY live comparison and manual paper positions."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.security import get_current_user
from app.services import bank_options_positions, bank_options_service

router = APIRouter(prefix="/api/bank-options", tags=["bank-options"])


class OpenPosition(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    bankex_security_id: str = Field(min_length=1, max_length=40)
    banknifty_security_id: str = Field(min_length=1, max_length=40)
    side: Literal["CE", "PE"]
    bankex_lots: int = Field(default=1, ge=1, le=100, strict=True)
    banknifty_lots: int = Field(default=1, ge=1, le=100, strict=True)
    request_id: str = Field(min_length=1, max_length=80)


@router.get("/live")
def live(
    side: Literal["both", "CE", "PE"] = "both",
    range_points: Annotated[int, Query(ge=100, le=3500,
        description="Legacy setting; the display always uses ATM ± seven 500-point BANKEX strikes.")] = 3500,
    liquidity: Literal["liquid", "all"] = "all",
    min_volume: Annotated[int, Query(ge=0, le=1_000_000_000)] = 1,
    max_spread_pct: Annotated[float, Query(gt=0, le=200, allow_inf_nan=False)] = 10,
    bankex_lots: Annotated[int, Query(ge=1, le=100)] = 1,
    banknifty_lots: Annotated[int, Query(ge=1, le=100)] = 1,
    metric: Literal["points", "divided", "rupees"] = "divided",
    divisor: Annotated[float, Query(ge=0.01, le=1_000_000, allow_inf_nan=False)] = 30,
    user: str = Depends(get_current_user),
):
    return bank_options_service.get_live(side=side, range_points=range_points, liquidity=liquidity,
        min_volume=min_volume, max_spread_pct=max_spread_pct, bankex_lots=bankex_lots,
        banknifty_lots=banknifty_lots, metric=metric, divisor=divisor)


@router.get("/positions")
def positions(user: str = Depends(get_current_user)):
    return bank_options_positions.list_positions(user)


@router.post("/positions", status_code=201)
def create_position(body: OpenPosition, user: str = Depends(get_current_user)):
    try:
        return bank_options_positions.create_position(user, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/positions/{position_id}/close")
def close_position(position_id: int, user: str = Depends(get_current_user)):
    try:
        return bank_options_positions.close_position(user, position_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
