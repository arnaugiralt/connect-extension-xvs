import copy
from io import BufferedReader

import pytest

from unittest.mock import patch

from sqlalchemy import null

from connect_ext_ppr.models.deployment import Deployment, DeploymentRequest
from connect_ext_ppr.models.enums import (
    CBCTaskLogStatus,
    DeploymentRequestStatusChoices,
    DeploymentStatusChoices,
    TasksStatusChoices,
    TaskTypesChoices,
)
from connect_ext_ppr.client.exception import ClientError
from connect_ext_ppr.models.task import Task
from connect_ext_ppr.tasks_manager import (
    _check_cbc_task_status,
    _send_ppr,
    apply_ppr_and_delegate_to_marketplaces,
    check_and_update_product,
    delegate_to_l2,
    main_process,
    TaskException,
)
from connect_ext_ppr.services.cbc_hub import CBCService

from tests.test_utils import check_excel_file_column_values


def test_apply_ppr_and_delegate_to_marketplaces(deployment_request_factory):
    assert apply_ppr_and_delegate_to_marketplaces(deployment_request_factory())


def test__send_ppr(parse_ppr_success_response, sample_ppr_file, mocker):
    cbc_service = mocker.Mock()
    cbc_service.parse_ppr.return_value = parse_ppr_success_response
    cbc_service.apply_ppr.return_value = 100
    assert _send_ppr(cbc_service, sample_ppr_file)


def test__send_ppr_max_retries(sample_ppr_file, mocker):
    cbc_service = mocker.Mock()
    cbc_service.parse_ppr.side_effect = ClientError('Some random error')
    with pytest.raises(TaskException) as ex:
        _send_ppr(cbc_service, sample_ppr_file)
        assert str(ex) == 'Some random error'


def test__check_cbc_task_status(task_logs_response, mocker):
    not_started_log = copy.deepcopy(task_logs_response)
    not_started_log[0]['status'] = CBCTaskLogStatus.not_started
    cbc_service = mocker.Mock()
    cbc_service.search_task_logs_by_name.side_effect = [
        not_started_log,
        task_logs_response,
    ]
    with mocker.patch('connect_ext_ppr.tasks_manager.time.sleep', return_value=None):
        assert _check_cbc_task_status(cbc_service, 100)


def test__check_cbc_task_status_with_max_retries(task_logs_response, mocker):
    not_started_log = copy.deepcopy(task_logs_response)
    not_started_log[0]['status'] = CBCTaskLogStatus.not_started
    cbc_service = mocker.Mock()
    cbc_service.search_task_logs_by_name.side_effect = ClientError('Some random error')
    with mocker.patch('connect_ext_ppr.tasks_manager.time.sleep', return_value=None):
        with pytest.raises(TaskException) as ex:
            _check_cbc_task_status(cbc_service, 100)
            assert str(ex) == 'Some random error'


@patch.object(CBCService, 'update_product')
@patch.object(CBCService, 'get_product_details')
@patch.object(CBCService, '__init__')
def test_check_and_update_product(
    mock___init__,
    mock_get_product_details,
    mock_update_product,
    product_details,
    update_product_response,
    deployment_request_factory,
):

    mock___init__.return_value = None
    product_details['isUpdateAvailable'] = True
    mock_get_product_details.return_value = product_details
    mock_update_product.return_value = update_product_response

    assert check_and_update_product(
        deployment_request=deployment_request_factory(), cbc_service=CBCService(),
    )
    assert mock_get_product_details.call_count == 1
    assert mock_update_product.call_count == 1


@patch.object(CBCService, 'update_product')
@patch.object(CBCService, 'get_product_details')
@patch.object(CBCService, '__init__')
def test_check_and_update_product_no_update_needed(
    mock___init__,
    mock_get_product_details,
    mock_update_product,
    product_details,
    update_product_response,
    deployment_request_factory,
):

    mock___init__.return_value = None
    product_details['isUpdateAvailable'] = False
    mock_get_product_details.return_value = product_details
    mock_update_product.return_value = update_product_response

    assert check_and_update_product(
        deployment_request=deployment_request_factory(), cbc_service=CBCService(),
    )
    assert mock_get_product_details.call_count == 1
    assert mock_update_product.call_count == 0


@patch.object(CBCService, 'update_product')
@patch.object(CBCService, 'get_product_details')
@patch.object(CBCService, '__init__')
def test_check_and_update_product_manually(
    mock___init__,
    mock_get_product_details,
    mock_update_product,
    product_details,
    update_product_response,
    deployment_request_factory,
):

    mock___init__.return_value = None
    product_details['isUpdateAvailable'] = True
    mock_get_product_details.return_value = product_details
    mock_update_product.return_value = update_product_response

    assert check_and_update_product(
        deployment_request=deployment_request_factory(manually=True), cbc_service=CBCService(),
    )

    assert mock_get_product_details.call_count == 0
    assert mock_update_product.call_count == 0


@patch.object(CBCService, 'get_product_details')
@patch.object(CBCService, '__init__')
def test_check_and_update_product_w_errors_in_get_details(
    mock___init__,
    mock_get_product_details,
    get_product_details_not_found_response,
    deployment_request_factory,
):
    mock___init__.return_value = None
    mock_get_product_details.return_value = get_product_details_not_found_response

    with pytest.raises(Exception):
        check_and_update_product(
            deployment_request=deployment_request_factory(), cbc_service=CBCService(),
        )


@patch.object(CBCService, 'update_product')
@patch.object(CBCService, 'get_product_details')
@patch.object(CBCService, '__init__')
def test_check_and_update_product_w_errors_in_update_product(
    mock___init__,
    mock_get_product_details,
    mock_update_product,
    product_details,
    product_not_installed_response,
    deployment_request_factory,
):
    mock___init__.return_value = None
    product_details['isUpdateAvailable'] = True
    mock_get_product_details.return_value = product_details
    mock_update_product.return_value = product_not_installed_response

    with pytest.raises(Exception):
        check_and_update_product(
            deployment_request=deployment_request_factory(), cbc_service=CBCService(),
        )


@patch.object(CBCService, '__init__')
def test_delegate_to_l2(
    mock___init__,
    connect_client,
    deployment_request_factory,
    mocker,
):
    mock___init__.return_value = None
    cbc_sevice = CBCService()
    ppr_file_data = open('./tests/fixtures/test_PPR_file_delegate_l2.xlsx', 'rb').read()
    assert not check_excel_file_column_values(
        ppr_file_data, 'OpUnitServicePlans', 'Published', True,
    )
    assert not check_excel_file_column_values(ppr_file_data, 'ServicePlans', 'Published', False)

    file_sent = null

    def send_ppr_side_effect(*args):
        nonlocal file_sent
        file_sent = args[1].read()

    send_ppr_mock = mocker.patch(
        'connect_ext_ppr.tasks_manager._send_ppr',
        return_value=101,
        side_effect=send_ppr_side_effect,
    )

    get_from_media_mock = mocker.patch(
        'connect_ext_ppr.tasks_manager.get_ppr_from_media',
        return_value=ppr_file_data,
    )
    create_dr_file_to_media_mock = mocker.patch(
        'connect_ext_ppr.tasks_manager.create_dr_file_to_media',
    )
    check_cbc_task_status_mock = mocker.patch(
        'connect_ext_ppr.tasks_manager._check_cbc_task_status',
    )

    assert delegate_to_l2(
        deployment_request=deployment_request_factory(),
        cbc_service=cbc_sevice,
        connect_client=connect_client,
    )

    assert get_from_media_mock.call_count == 1
    assert create_dr_file_to_media_mock.call_count == 1
    assert send_ppr_mock.call_count == 1
    assert check_cbc_task_status_mock.call_count == 1

    assert send_ppr_mock.call_args.args[0] == cbc_sevice
    ppr_file_arg = send_ppr_mock.call_args.args[1]
    assert isinstance(ppr_file_arg, BufferedReader)
    assert check_excel_file_column_values(file_sent, 'OpUnitServicePlans', 'Published', True)
    assert check_excel_file_column_values(file_sent, 'ServicePlans', 'Published', False)


@patch.object(CBCService, '__init__')
def test_delegate_to_l2_manually(
    mock___init__,
    connect_client,
    deployment_request_factory,
    mocker,
):
    mock___init__.return_value = None
    cbc_sevice = CBCService()

    send_ppr_mock = mocker.patch(
        'connect_ext_ppr.tasks_manager._send_ppr',
    )
    get_from_media_mock = mocker.patch(
        'connect_ext_ppr.tasks_manager.get_ppr_from_media',
    )
    create_dr_file_to_media_mock = mocker.patch(
        'connect_ext_ppr.tasks_manager.create_dr_file_to_media',
    )
    check_cbc_task_status_mock = mocker.patch(
        'connect_ext_ppr.tasks_manager._check_cbc_task_status',
    )

    assert delegate_to_l2(
        deployment_request=deployment_request_factory(manually=True),
        cbc_service=cbc_sevice,
        connect_client=connect_client,
    )

    assert get_from_media_mock.call_count == 0
    assert create_dr_file_to_media_mock.call_count == 0
    assert send_ppr_mock.call_count == 0
    assert check_cbc_task_status_mock.call_count == 0


@patch.object(CBCService, '__init__')
def test_delegate_to_l2_processing_error(
    mock___init__,
    connect_client,
    deployment_request_factory,
    mocker,
):
    mock___init__.return_value = None
    cbc_sevice = CBCService()
    ppr_file_data = open('./tests/fixtures/test_PPR_file_delegate_l2.xlsx', 'rb').read()

    send_ppr_mock = mocker.patch(
        'connect_ext_ppr.tasks_manager._send_ppr',
        return_value=101,
    )
    get_from_media_mock = mocker.patch(
        'connect_ext_ppr.tasks_manager.get_ppr_from_media',
        return_value=ppr_file_data,
    )
    process_ppr_file_for_delelegate_l2_mock = mocker.patch(
        'connect_ext_ppr.tasks_manager.process_ppr_file_for_delelegate_l2',
        side_effect=ValueError('Wrong value "Cthulhu"'),
    )
    create_dr_file_to_media_mock = mocker.patch(
        'connect_ext_ppr.tasks_manager.create_dr_file_to_media',
    )
    check_cbc_task_status_mock = mocker.patch(
        'connect_ext_ppr.tasks_manager._check_cbc_task_status',
    )

    with pytest.raises(TaskException) as e:
        delegate_to_l2(
            deployment_request=deployment_request_factory(),
            cbc_service=cbc_sevice,
            connect_client=connect_client,
        )
    assert str(e.value) == 'Error while processing PPR file: Wrong value "Cthulhu"'

    assert get_from_media_mock.call_count == 1
    assert process_ppr_file_for_delelegate_l2_mock.call_count == 1
    assert create_dr_file_to_media_mock.call_count == 0
    assert send_ppr_mock.call_count == 0
    assert check_cbc_task_status_mock.call_count == 0


@patch.object(CBCService, 'get_product_details')
@patch.object(CBCService, '__init__', return_value=None)
def test_main_process(
    _,
    mock_get_product_details,
    dbsession,
    deployment_factory,
    deployment_request_factory,
    task_factory,
    ppr_version_factory,
    connect_client,
    mock_tasks,
    mocker,
    product_details,
):
    mock_get_product_details.return_value = product_details
    dep = deployment_factory()
    ppr = ppr_version_factory(id='PPR-123', product_version=1, deployment=dep)
    dr = deployment_request_factory(deployment=dep, delegate_l2=True, ppr=ppr)
    task_factory(deployment_request=dr, task_index='0001', type=TaskTypesChoices.product_setup)
    task_factory(deployment_request=dr, task_index='0002', type=TaskTypesChoices.apply_and_delegate)
    task_factory(deployment_request=dr, task_index='0003', type=TaskTypesChoices.delegate_to_l2)

    mocker.patch('connect_ext_ppr.tasks_manager._get_cbc_service', return_value=CBCService())
    assert main_process(dr.id, {}, connect_client) == DeploymentRequestStatusChoices.done

    assert dbsession.query(Deployment).filter_by(status=DeploymentStatusChoices.synced).count() == 1
    assert dbsession.query(DeploymentRequest).filter_by(
        status=DeploymentRequestStatusChoices.done,
    ).count() == 1
    assert dbsession.query(Task).filter(
        Task.status == TasksStatusChoices.done,
        Task.started_at.is_not(null()),
        Task.finished_at.is_not(null()),
    ).count() == 3


@patch.object(CBCService, 'get_product_details')
@patch.object(CBCService, '__init__', return_value=None)
def test_main_process_wo_l2_delegation(
    _,
    mock_get_product_details,
    dbsession,
    deployment_factory,
    deployment_request_factory,
    task_factory,
    ppr_version_factory,
    connect_client,
    mock_tasks,
    mocker,
    product_details,
):
    mock_get_product_details.return_value = product_details
    dep = deployment_factory()
    ppr = ppr_version_factory(id='PPR-123', product_version=1, deployment=dep)
    dr = deployment_request_factory(deployment=dep, delegate_l2=False, ppr=ppr)
    task_factory(deployment_request=dr, task_index='0001', type=TaskTypesChoices.product_setup)
    task_factory(deployment_request=dr, task_index='0002', type=TaskTypesChoices.apply_and_delegate)

    mocker.patch('connect_ext_ppr.tasks_manager._get_cbc_service', return_value=CBCService())
    assert main_process(dr.id, {}, connect_client) == DeploymentRequestStatusChoices.done

    assert dbsession.query(Deployment).filter_by(
        status=DeploymentStatusChoices.pending,
    ).count() == 1
    assert dbsession.query(DeploymentRequest).filter_by(
        status=DeploymentRequestStatusChoices.done,
    ).count() == 1
    assert dbsession.query(Task).filter(
        Task.status == TasksStatusChoices.done,
        Task.started_at.is_not(null()),
        Task.finished_at.is_not(null()),
    ).count() == 2


@patch.object(CBCService, 'get_product_details')
@patch.object(CBCService, '__init__', return_value=None)
def test_main_process_deployment_w_new_ppr_version(
    _,
    mock_get_product_details,
    dbsession,
    file_factory,
    deployment_factory,
    deployment_request_factory,
    task_factory,
    ppr_version_factory,
    connect_client,
    mock_tasks,
    mocker,
    product_details,
):
    mock_get_product_details.return_value = product_details
    ppr_file = file_factory(id='MFL-123')
    dep = deployment_factory()
    dr_ppr = ppr_version_factory(
        id='PPR-1234', file=ppr_file.id, product_version=1, deployment=dep)
    ppr_version_factory(id='PPR-123', product_version=2, deployment=dep)
    dr = deployment_request_factory(deployment=dep, delegate_l2=False, ppr=dr_ppr)
    task_factory(deployment_request=dr, task_index='0001', type=TaskTypesChoices.product_setup)
    task_factory(deployment_request=dr, task_index='0002', type=TaskTypesChoices.apply_and_delegate)
    task_factory(deployment_request=dr, task_index='0003', type=TaskTypesChoices.delegate_to_l2)

    mocker.patch('connect_ext_ppr.tasks_manager._get_cbc_service', return_value=CBCService())
    assert main_process(dr.id, {}, connect_client) == DeploymentRequestStatusChoices.done

    assert dbsession.query(Deployment).filter_by(
        status=DeploymentStatusChoices.pending,
    ).count() == 1
    assert dbsession.query(DeploymentRequest).filter_by(
        status=DeploymentRequestStatusChoices.done,
    ).count() == 1
    assert dbsession.query(Task).filter(
        Task.status == TasksStatusChoices.done,
        Task.started_at.is_not(null()),
        Task.finished_at.is_not(null()),
    ).count() == 3


@patch.object(CBCService, '__init__', return_value=None)
@pytest.mark.parametrize(
    ('type_function_to_mock', 'done_tasks', 'tasks_w_errors', 'pending_tasks'),
    (
        (TaskTypesChoices.product_setup, 0, 1, 2),
        (TaskTypesChoices.apply_and_delegate, 1, 1, 1),
        (TaskTypesChoices.delegate_to_l2, 2, 1, 0),
    ),
)
def test_main_process_ends_w_error(
    _,
    dbsession,
    deployment_factory,
    deployment_request_factory,
    done_tasks,
    tasks_w_errors,
    pending_tasks,
    type_function_to_mock,
    mocker,
    task_factory,
    ppr_version_factory,
    connect_client,
    mock_tasks,
):
    dep = deployment_factory()
    ppr = ppr_version_factory(id='PPR-123', product_version=1, deployment=dep, version=1)
    dr = deployment_request_factory(deployment=dep, delegate_l2=True, ppr=ppr)
    task_factory(deployment_request=dr, task_index='0001', type=TaskTypesChoices.product_setup)
    task_factory(deployment_request=dr, task_index='0002', type=TaskTypesChoices.apply_and_delegate)
    task_factory(deployment_request=dr, task_index='0003', type=TaskTypesChoices.delegate_to_l2)

    my_mock = mocker.Mock()

    def mock_get(key):
        return lambda **kwargs: key != type_function_to_mock

    my_mock.get = mock_get

    mocker.patch('connect_ext_ppr.tasks_manager._get_cbc_service', return_value=CBCService())
    mocker.patch('connect_ext_ppr.tasks_manager.TASK_PER_TYPE', my_mock)
    assert main_process(dr.id, {}, connect_client) == DeploymentRequestStatusChoices.error

    assert dbsession.query(Deployment).filter_by(
        status=DeploymentStatusChoices.pending,
    ).count() == 1
    assert dbsession.query(DeploymentRequest).filter_by(
        status=DeploymentRequestStatusChoices.error,
    ).count() == 1

    assert dbsession.query(Task).filter(
        Task.status == TasksStatusChoices.done,
        Task.started_at.is_not(null()),
        Task.finished_at.is_not(null()),
    ).count() == done_tasks
    assert dbsession.query(Task).filter(
        Task.status == TasksStatusChoices.error,
        Task.started_at.is_not(null()),
        Task.finished_at.is_not(null()),
    ).count() == tasks_w_errors
    assert dbsession.query(Task).filter(
        Task.status == TasksStatusChoices.pending,
        Task.started_at.is_(null()),
        Task.finished_at.is_(null()),
    ).count() == pending_tasks


@patch.object(CBCService, '__init__', return_value=None)
@pytest.mark.parametrize(
    ('task_statuses', 'done_tasks', 'aborted_tasks'),
    (
        (
            [TasksStatusChoices.aborted, TasksStatusChoices.aborted, TasksStatusChoices.aborted],
            0,
            3,
        ),
        (
            [TasksStatusChoices.done, TasksStatusChoices.aborted, TasksStatusChoices.aborted],
            1,
            2,
        ),
        (
            [TasksStatusChoices.done, TasksStatusChoices.pending, TasksStatusChoices.aborted],
            2,
            1,
        ),
    ),
)
def test_main_process_w_aborted_tasks(
    _,
    dbsession,
    deployment_factory,
    deployment_request_factory,
    task_factory,
    ppr_version_factory,
    task_statuses,
    done_tasks,
    aborted_tasks,
    connect_client,
    mock_tasks,
    mocker,
):
    """
        We only process DeploymentRequest that are in Pending status. So in this case we asume that
        the DR is in Pending status at the begining, but changes it's
    """
    dep = deployment_factory()
    ppr = ppr_version_factory(id='PPR-123', product_version=1, deployment=dep, version=1)
    dr = deployment_request_factory(
        deployment=dep,
        delegate_l2=True,
        ppr=ppr,
        status=DeploymentRequestStatusChoices.pending,
    )
    task_factory(
        deployment_request=dr,
        task_index='0001',
        type=TaskTypesChoices.product_setup,
        status=task_statuses.pop(),
    )

    task_factory(
        deployment_request=dr,
        task_index='0002',
        type=TaskTypesChoices.apply_and_delegate,
        status=task_statuses.pop(),
    )
    task_factory(
        deployment_request=dr,
        task_index='0003',
        type=TaskTypesChoices.delegate_to_l2,
        status=task_statuses.pop(),
    )

    def change_dr_status(instance, attribute_names=None, with_for_update=None):
        if isinstance(instance, DeploymentRequest):
            instance.status = DeploymentRequestStatusChoices.aborting
        return instance

    dbsession.refresh = change_dr_status
    mocker.patch('connect_ext_ppr.tasks_manager._get_cbc_service', return_value=CBCService())

    assert main_process(dr.id, {}, connect_client) == DeploymentRequestStatusChoices.aborted

    assert dbsession.query(Deployment).filter_by(
        status=DeploymentStatusChoices.pending,
    ).count() == 1
    assert dbsession.query(DeploymentRequest).filter_by(
        status=DeploymentRequestStatusChoices.aborted,
    ).count() == 1

    assert dbsession.query(Task).filter(
        Task.status == TasksStatusChoices.done,
    ).count() == done_tasks
    assert dbsession.query(Task).filter(
        Task.status == TasksStatusChoices.aborted,
    ).count() == aborted_tasks


@patch.object(CBCService, '__init__', return_value=None)
def test_main_process_w_aborted_deployment_request(
    _,
    dbsession,
    deployment_factory,
    deployment_request_factory,
    task_factory,
    ppr_version_factory,
    connect_client,
    mock_tasks,
):
    """
        We only process DeploymentRequest that are in Pending status. So in this case we asume that
        the DR is in Pending status at the begining, but changes it's
    """
    dep = deployment_factory()
    ppr = ppr_version_factory(id='PPR-123', product_version=1, deployment=dep, version=1)
    dr = deployment_request_factory(
        deployment=dep,
        delegate_l2=True,
        ppr=ppr,
        status=DeploymentRequestStatusChoices.aborted,
    )
    task_factory(
        deployment_request=dr,
        task_index='0001',
        type=TaskTypesChoices.product_setup,
        status=TasksStatusChoices.aborted,
    )

    task_factory(
        deployment_request=dr,
        task_index='0002',
        type=TaskTypesChoices.apply_and_delegate,
        status=TasksStatusChoices.aborted,
    )
    task_factory(
        deployment_request=dr,
        task_index='0003',
        type=TaskTypesChoices.delegate_to_l2,
        status=TasksStatusChoices.aborted,
    )

    assert main_process(dr.id, {}, connect_client) == DeploymentRequestStatusChoices.aborted

    assert dbsession.query(Deployment).filter_by(
        status=DeploymentStatusChoices.pending,
    ).count() == 1
    assert dbsession.query(DeploymentRequest).filter_by(
        status=DeploymentRequestStatusChoices.aborted,
    ).count() == 1

    assert dbsession.query(Task).filter(
        Task.status == TasksStatusChoices.aborted,
    ).count() == 3


@patch.object(CBCService, '__init__', return_value=None)
@pytest.mark.parametrize(
    ('type_function_to_mock', 'done_tasks', 'tasks_w_errors', 'pending_tasks'),
    (
        (TaskTypesChoices.product_setup, 0, 1, 2),
        (TaskTypesChoices.apply_and_delegate, 1, 1, 1),
        (TaskTypesChoices.delegate_to_l2, 2, 1, 0),
    ),
)
def test_main_process_ends_w_task_exception(
    _,
    dbsession,
    deployment_factory,
    deployment_request_factory,
    done_tasks,
    tasks_w_errors,
    pending_tasks,
    type_function_to_mock,
    mocker,
    task_factory,
    ppr_version_factory,
    connect_client,
    mock_tasks,
):
    dep = deployment_factory()
    ppr = ppr_version_factory(id='PPR-123', product_version=1, deployment=dep, version=1)
    dr = deployment_request_factory(deployment=dep, delegate_l2=True, ppr=ppr)
    task_factory(deployment_request=dr, task_index='0001', type=TaskTypesChoices.product_setup)
    task_factory(deployment_request=dr, task_index='0002', type=TaskTypesChoices.apply_and_delegate)
    task_factory(deployment_request=dr, task_index='0003', type=TaskTypesChoices.delegate_to_l2)

    my_mock = mocker.Mock()

    def mock_get(key):
        if key == type_function_to_mock:
            raise Exception('Unexpected Error')
        return lambda **kwargs: True

    my_mock.get = mock_get

    mocker.patch('connect_ext_ppr.tasks_manager.TASK_PER_TYPE', my_mock)
    mocker.patch('connect_ext_ppr.tasks_manager._get_cbc_service', return_value=CBCService())
    assert main_process(dr.id, {}, connect_client) == DeploymentRequestStatusChoices.error

    assert dbsession.query(Deployment).filter_by(
        status=DeploymentStatusChoices.pending,
    ).count() == 1
    assert dbsession.query(DeploymentRequest).filter_by(
        status=DeploymentRequestStatusChoices.error,
    ).count() == 1

    assert dbsession.query(Task).filter(
        Task.status == TasksStatusChoices.done,
        Task.started_at.is_not(null()),
        Task.finished_at.is_not(null()),
    ).count() == done_tasks
    assert dbsession.query(Task).filter(
        Task.status == TasksStatusChoices.error,
        Task.started_at.is_not(null()),
        Task.finished_at.is_not(null()),
    ).count() == tasks_w_errors
    assert dbsession.query(Task).filter(
        Task.status == TasksStatusChoices.pending,
        Task.started_at.is_(null()),
        Task.finished_at.is_(null()),
    ).count() == pending_tasks
