from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", include_in_schema=False)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/recipients", include_in_schema=False)
def recipients_page(request: Request):
    """
    Renders recipients UI which fetches data via the API.
    """
    return templates.TemplateResponse("recipients.html", {"request": request})


@router.get("/campaigns", include_in_schema=False)
def campaigns_page(request: Request):
    """
    Renders campaigns UI which fetches data via the API.
    """
    return templates.TemplateResponse("campaigns.html", {"request": request})