"""
torchcrepe model for HEAR 2021 NeurIPS competition.
"""

from typing import Tuple

import torch
import torchcrepe
from torch import Tensor

HOP_SIZE = 25


class TorchCrepeModel(torch.nn.Module):
    """
    A pretty gross wrapper on torchcrepe, because of its implicit
    model loading: https://github.com/maxrmorrison/torchcrepe/issues/13
    """

    # sample rate and embedding sizes are required model attributes for the HEAR API
    sample_rate = 16000
    # ???
    embedding_size = 768
    scene_embedding_size = embedding_size
    timestamp_embedding_size = embedding_size

    def __init__(self):
        super().__init__()

        # This is gross.
        if torch.cuda.is_available():
            torchcrepe.load.model(device="cuda", capacity="full")
        else:
            torchcrepe.load.model(device="cpu", capacity="full")

    def forward(self, x: Tensor):
        # Or do x.device?
        if torch.cuda.is_available():
            device = "cuda"
        else:
            device = "cpu"
        if x.ndim == 1:
            x = x.view(1, x.shape[0])

        assert x.ndim == 2

        # This is lame, sorry
        # torchcrepe only can process one audio at a time
        embeddings = []
        for i in range(x.shape[0]):
            embeddings.append(
                torchcrepe.embed(
                    audio=x[i].view(1, x.shape[1]),
                    sample_rate=self.sample_rate,
                    hop_length=HOP_SIZE,
                    model="full",
                    device=device,
                    pad=True,
                )
            )
        embeddings = torch.stack(embeddings)
        return embeddings


def load_model(model_file_path: str = "") -> torch.nn.Module:
    """
    Returns a torch.nn.Module that produces embeddings for a frame of audio.

    Args:
        model_file_path: Load model checkpoint from this file path. For this baseline,
            if no path is provided then the default random init weights for the
            linear projection layer will be used.
    Returns:
        Model: torch.nn.Module loaded on the specified device.
    """
    return TorchCrepeModel()


def get_timestamp_embeddings(
    audio: Tensor,
    model: torch.nn.Module,
) -> Tuple[Tensor, Tensor]:
    """
    This function returns embeddings at regular intervals centered at timestamps. Both
    the embeddings and corresponding timestamps (in milliseconds) are returned.

    Args:
        audio: n_sounds x n_samples of mono audio in the range [-1, 1].
        model: Loaded model.

    Returns:
        - Tensor: embeddings, A float32 Tensor with shape (n_sounds, n_timestamps,
            model.timestamp_embedding_size).
        - Tensor: timestamps, Centered timestamps in milliseconds corresponding
            to each embedding in the output. Shape: (n_sounds, n_timestamps).
    """

    # Assert audio is of correct shape
    if audio.ndim != 2:
        raise ValueError(
            "audio input tensor must be 2D with shape (n_sounds, num_samples)"
        )

    # Make sure the correct model type was passed in
    if not isinstance(model, TorchCrepeModel):
        raise ValueError(f"Model must be an instance of {TorchCrepeModel.__name__}")

    # Send the model to the same device that the audio tensor is on.
    # model = model.to(audio.device)

    # Put the model into eval mode, and not computing gradients while in inference.
    # Iterate over all batches and accumulate the embeddings for each frame.
    model.eval()
    with torch.no_grad():
        embeddings = model(audio)

    # Length of the audio in MS
    audio_ms = int(audio.shape[1] / model.sample_rate * 1000)

    # samples => timestamps
    # 31439 => 97
    # 31440 => 98
    # This is weird that its 5ms, not half the hopsize of 20
    ntimestamps = (audio_ms - 5) // 20

    # Also
    # 32000 => 99
    # 32080 => 100

    # I don't know if this is their exact centering, but this matches
    # their shape.
    last_center = 12.5 + (ntimestamps - 1) * 20
    timestamps = torch.arange(12.5, last_center + 20, 20)
    assert len(timestamps) == ntimestamps
    timestamps = timestamps.expand((embeddings.shape[0], timestamps.shape[0]))
    assert timestamps.shape[1] == embeddings.shape[1]
    timestamps = torch.zeros((embeddings.shape[0], embeddings.shape[1]))

    return embeddings, timestamps


# TODO: There must be a better way to do scene embeddings,
# e.g. just truncating / padding the audio to 2 seconds
# and concatenating a subset of the embeddings.
def get_scene_embeddings(
    audio: Tensor,
    model: torch.nn.Module,
) -> Tensor:
    """
    This function returns a single embedding for each audio clip. In this baseline
    implementation we simply summarize the temporal embeddings from
    get_timestamp_embeddings() using torch.mean().

    Args:
        audio: n_sounds x n_samples of mono audio in the range [-1, 1]. All sounds in
            a batch will be padded/trimmed to the same length.
        model: Loaded model.

    Returns:
        - embeddings, A float32 Tensor with shape
            (n_sounds, model.scene_embedding_size).
    """
    embeddings, _ = get_timestamp_embeddings(audio, model)
    embeddings = torch.mean(embeddings, dim=1)
    return embeddings
